# -*- coding: utf-8 -*-
"""The export preview asks what the page is NOW, not what it was at load.

lee, with a balloon whose typesetting had stroke-shaped holes in it: *"teh
exported preview is still diferent than teh live view... all teh spot that
dont show in teh exported vuiew are all area that i manualy did something
to... wheni move something in the live view it dont update inteh exported
view"*.

The page he sent was chased all the way down: his plate is clean, his paint
stroke is in the under band, and this build renders his page 010 perfectly.
The picture he was looking at was not drawn wrong - it was OLD. The preview's
URL carries a key the browser was handed when the page loaded, the image is
served immutable, and after any edit that stale key is not a wrong answer
from the server: it is the browser re-showing its own old copy WITHOUT
ASKING. Every "difference" was one of his own edits, frozen out of the
preview since the page was opened.

The first fix made the preview re-fetch its key before every settle
(`/api/page/<i>/keys`). The second went further, on lee's word (*"fix it or
replace ith with a better system"*): the preview now carries NO key at all -
the unkeyed render is served no-store, the browser keeps nothing, and the
server's own caches make every settle a few milliseconds. The keys endpoint
stays for the main-view images, which still key honestly.

Also pinned here:

* the warm-up nudge on every page change is FREE once the chapter is built -
  it used to start a whole new warm-up, count all 46 jobs again, and flash
  the bar over a walk of pure cache hits (*"when i swithc fast thsi show up
  for a few second and complets fast"*);
* the page-loading screen exists and `showPage` holds switching while a
  page's picture is on its way (*"add a loading screen that prevents teh
  user to switch page while a page is loading and mak te loading screen be
  teh app icon witha circle arond it"*).
"""
import json
import os
import shutil
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")


def _project(root, pages=1):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    for n in range(pages):
        img = np.full((300, 240, 3), 246, np.uint8)
        cv2.rectangle(img, (30, 40), (200, 150), (0, 0, 0), 2)
        p.add_uploaded("p%d.png" % n, cv2.imencode(".png", img)[1].tobytes())
        p.pages[n].regions = [{
            "id": 1, "kind": "bubble", "order": 0, "bbox": [40, 50, 150, 90],
            "bubble_bbox": [32, 42, 166, 106],
            "polygon": [[40, 50], [190, 50], [190, 140], [40, 140]],
            "src_text": "テスト", "dst_text": "HELLO", "confidence": 0.9}]
        p.pages[n].detected = True
        p.pages[n].cleaned = True
    return p


# --------------------------------------------------------------- the keys

def test_the_keys_endpoint_says_what_the_page_is_now():
    from mangatl import editor
    root = scratch("_tmp_keys_now")
    p = _project(root)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        def keys():
            with urllib.request.urlopen(base + "/api/page/0/keys",
                                        timeout=20) as r:
                return json.loads(r.read())
        a = keys()
        assert a.get("tkey") and a.get("vkey")
        assert keys() == a, "asking twice moved the key - nothing changed"

        # An edit. The words moved, so the finished page is a different
        # picture - and the key must say so, or the browser re-shows its old
        # copy without ever asking the server.
        p.pages[0].regions[0]["dst_text"] = "SOMETHING ELSE ENTIRELY"
        b = keys()
        assert b["tkey"] != a["tkey"], \
            "the page changed and its key did not - the stale-preview bug"
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_preview_carries_no_cache_key_at_all():
    """The keyed design is GONE, on lee's word: *"i wan t you to look at how
    teh expoted preivew is made and fix it or replace ith with a better
    system"*. A key meant "immutable, max-age one year", so any slip on the
    client - a stale key, a race, a tab running old code - made the browser
    re-show year-old bytes for ever, and a day was lost to exactly that.
    No key, no client cache, nothing left that CAN go stale."""
    import mangatl
    js = open(os.path.join(os.path.dirname(os.path.abspath(
        mangatl.__file__)), "static", "js", "exactview.js"),
        encoding="utf-8").read()
    fn = js.split("function exactUrl")[1].split("\n}")[0]
    assert "v=" not in fn, "the preview URL grew a cache key back"
    load = js.split("async function exactLoad")[1].split("\nfunction ")[0]
    assert "/keys" not in load, \
        "exactLoad depends on key plumbing again - the design this replaced"


def test_the_unkeyed_render_is_never_cached_and_always_current():
    """The whole guarantee, end to end, with zero client cooperation: ask,
    edit, ask again - the second answer shows the edit, and the header says
    the browser may keep nothing."""
    from mangatl import editor
    root = scratch("_tmp_nostore")
    p = _project(root)
    editor.do_typeset(p, 0)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        def render():
            with urllib.request.urlopen(
                    base + "/render/0?mode=typeset&ro=1", timeout=60) as r:
                return r.read(), r.headers.get("Cache-Control", "")
        a, cache = render()
        assert "no-store" in cache, \
            "an unkeyed render is cacheable: %r" % cache
        p.pages[0].regions[0]["dst_text"] = "SOMETHING ELSE ENTIRELY"
        p.pages[0].regions[0].pop("layout", None)
        b, _ = render()
        assert a != b, \
            "the page changed and the unkeyed render did not follow it"
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------- the nudge is free when idle

def test_a_built_chapter_takes_the_nudge_silently():
    """Once every page is made, the per-page-change nudge must not start a
    warm-up: no worker, no counter, no bar."""
    from mangatl import editor
    root = scratch("_tmp_warm_silent")
    p = _project(root, pages=2)
    try:
        for i in range(2):
            editor.do_typeset(p, i)
        editor.warm_pages(p, 0)
        for _ in range(400):
            if not editor._warm.get("running"):
                break
            time.sleep(0.05)
        assert not editor._warm.get("running")
        gen = editor._warm["gen"]

        # the chapter is built; every one of these is somebody turning a page
        for start in (1, 0, 1, 0):
            editor.warm_pages(p, start)
        time.sleep(0.2)
        assert editor._warm["gen"] == gen, \
            "a nudge on a built chapter started a new warm-up - the bar " \
            "lee saw flash on every fast page switch"
        assert not editor._warm.get("running")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_page_that_needs_building_still_gets_built():
    """The guard on the silence: filtering out finished work must not filter
    out real work, or the warm-up quietly stops warming."""
    from mangatl import editor
    root = scratch("_tmp_warm_still")
    p = _project(root, pages=1)
    try:
        editor.do_typeset(p, 0)
        gen = editor._warm["gen"]
        editor.warm_pages(p, 0)          # nothing built yet: real work
        assert editor._warm["gen"] == gen + 1, "the warm-up never started"
        for _ in range(400):
            if not editor._warm.get("running"):
                break
            time.sleep(0.05)
        assert not editor._warm.get("running")
        assert editor._warm["done"] == editor._warm["total"] > 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_landed_write_asks_the_preview_to_settle_again():
    """A layer's eye, a restack, a delete change the page without DRAWING
    anything, so the draw-triggered settle never fired and the preview sat
    on the old picture. lee: *"when i turn off tehhela layer or anythy other
    layer it dont update teh exported page"*. Every state-changing call goes
    through `api()`; the settle is asked for there, AFTER the server has the
    new state - which also closes the race of a settle outrunning its own
    save."""
    import mangatl
    js = open(os.path.join(os.path.dirname(os.path.abspath(
        mangatl.__file__)), "static", "js", "core.js"),
        encoding="utf-8").read()
    fn = js.split("const api=async")[1].split("\nfunction ")[0]
    assert "exactSoon" in fn, \
        "a write no longer re-settles the preview - eye toggles go stale"
    assert "!=='GET'" in fn or '!== "GET"' in fn.replace("'", '"'), \
        "reads re-settle too - every poll would bump the preview"


# ------------------------------------------------- a new server, a new page

def test_the_job_poll_carries_the_servers_run_id():
    """A tab opened before a restart keeps executing the JavaScript it loaded
    then - statics are no-store, but no header reaches into a tab that never
    asks again. Three fixes in one day "did not work" this way: the server
    was new, the tab was old. The poll carries the run id; the page reloads
    itself when it moves."""
    from mangatl import editor
    root = scratch("_tmp_boot_id")
    p = _project(root)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        def job():
            with urllib.request.urlopen(base + "/api/job", timeout=20) as r:
                return json.loads(r.read())
        a, b = job(), job()
        assert a.get("boot") and a["boot"] == b["boot"],             "the run id moved between two polls of one server"
        assert a["boot"] == editor._BOOT
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_page_reloads_when_the_run_id_moves():
    import mangatl
    src = open(os.path.join(os.path.dirname(os.path.abspath(
        mangatl.__file__)), "static", "js", "pipeline.js"),
        encoding="utf-8").read()
    fn = src.split("async function poll(")[1].split(
        "\nasync function ")[0]
    assert "j.boot" in fn and "location.reload()" in fn, \
        "an old tab can outlive the server again"
    assert fn.index("j.boot") < fn.index("paintJob("), \
        "the reload check runs after the bar was already painted stale"


# ------------------------------------------------------ the loading screen

def test_the_loading_screen_exists_and_holds_the_page():
    import mangatl
    base = os.path.join(os.path.dirname(os.path.abspath(mangatl.__file__)),
                        "static")
    html = open(os.path.join(base, "editor.html"), encoding="utf-8").read()
    assert 'id="pageLoading"' in html
    assert "icon.png" in html.split('id="pageLoading"')[1][:300], \
        "the loading screen is not the app icon"
    css = open(os.path.join(base, "css", "editor.css"),
               encoding="utf-8").read()
    assert "#pageLoading" in css and "pgspin" in css, \
        "no ring turns round the icon"
    js = open(os.path.join(base, "js", "frames.js"), encoding="utf-8").read()
    fn = js.split("async function showPage")[1]
    assert "pageHold" in fn.split("\n", 12)[0] or "pageHold" in fn[:600], \
        "showPage no longer holds switching while a page loads"
    assert "releasePages()" in js, "nothing ever takes the hold down"
