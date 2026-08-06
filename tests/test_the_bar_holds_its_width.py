"""A provider's answer must not be allowed to resize the top bar.

lee: *"the error moved everything out of the way"*. `#jobtxt` is `nowrap` and
`.side.right` is `flex:0 0 auto`, so a four-hundred-character error from a
provider made the job strip as wide as the sentence and pushed the page tools
off the bar entirely.

The fix is a strip that is the same size whatever it says: `.jobcol` is a fixed
250px, the message is cut with an ellipsis, the whole of it is on `title`, and
clicking it puts it in a toast that wraps.
"""
import re
import shutil
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from mangatl import editor
from mangatl.project import Project
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")

CSS = (PKG / "static" / "css" / "editor.css").read_text("utf-8")
LONG = ("Translating failed: " + "the provider said something extremely "
        "long about why it will not do that, " * 6)


# --------------------------------------------------- the shape of it, in CSS

def test_the_strip_is_a_fixed_width():
    """Not `flex:1 1 auto`. The bar it sits in cannot grow, so a strip that
    can takes its room from whatever is beside it."""
    m = re.search(r"\.jobcol\{([^}]*)\}", CSS, re.S)
    assert m, ".jobcol must be styled"
    rule = " ".join(m.group(1).split())
    assert "flex: 0 0 250px" in rule.replace("flex:0 0", "flex: 0 0"), rule
    assert "width:250px" in rule.replace(" ", ""), rule


def test_the_message_is_cut_rather_than_wrapped_or_grown():
    m = re.search(r"#jobtxt\{([^}]*)\}", CSS, re.S)
    rule = m.group(1).replace("\n", "").replace(" ", "")
    assert "white-space:nowrap" in rule
    assert "overflow:hidden" in rule
    assert "text-overflow:ellipsis" in rule


# ------------------------------------------------- what it says, in the browser

def _bar(fn):
    """The bar on a real page, with `paintJob` called directly.

    `paintJob` was split out of `poll` for exactly this: what the strip SAYS
    can be tested without a server that fails on cue, and without waiting out
    a poll interval to see it.
    """
    root = scratch("_tmp_barwidth")
    p = Project(None, root)
    p.add_uploaded("001.png", cv2.imencode(
        ".png", np.full((400, 300, 3), 240, np.uint8))[1].tobytes())
    p.save()
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1400, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            try:
                return fn(pg)
            finally:
                assert not errs, errs
    finally:
        srv.shutdown(); srv.server_close()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_a_four_hundred_character_error_does_not_move_the_bar():
    def check(pg):
        def width():
            return pg.evaluate("$('job').getBoundingClientRect().width")
        pg.evaluate("paintJob({running:false,done:0,total:0,error:''}, 0)")
        browserpool.settled(pg)
        calm = width()
        assert calm > 0
        pg.evaluate("paintJob({running:false,done:0,total:0,error:%r}, 0)"
                    % LONG)
        browserpool.settled(pg)
        assert width() == calm, "the error moved everything out of the way"
        # ...and a running label, which is the longest thing it says normally,
        # fits without being cut.
        pg.evaluate("paintJob({running:true,label:'Proofreading',"
                    "done:23,total:23}, 100)")
        browserpool.settled(pg)
        assert pg.evaluate(
            "$('jobtxt').scrollWidth <= $('jobtxt').clientWidth + 1"), \
            "the ordinary label should not need cutting"
    _bar(check)

    
def test_the_whole_message_is_still_reachable():
    def check(pg):
        pg.evaluate("paintJob({running:false,done:0,total:0,error:%r}, 0)"
                    % LONG)
        # cut on screen...
        assert pg.evaluate("$('jobtxt').scrollWidth > $('jobtxt').clientWidth")
        # ...whole on hover...
        assert pg.evaluate("$('job').title") == LONG
        # ...and whole in a toast that wraps, when clicked.
        pg.evaluate("showJobMessage()")
        browserpool.settled(pg)
        said = pg.evaluate("$('toast').textContent")
        assert said == LONG, said
        assert pg.evaluate(
            "getComputedStyle($('toast')).whiteSpace") != "nowrap"
    _bar(check)


def test_nothing_is_offered_when_there_is_nothing_more_to_see():
    """A pointer over "Ready" promising a message that does not exist."""
    def check(pg):
        pg.evaluate("paintJob({running:false,done:0,total:0}, 0)")
        assert pg.evaluate("$('job').title") == ""
        pg.evaluate("$('toast').textContent=''; showJobMessage()")
        assert pg.evaluate("$('toast').textContent") == ""
    _bar(check)


def test_the_page_tools_keep_their_place():
    """The thing lee actually saw: the buttons on the right of the bar went
    away when a run failed."""
    def check(pg):
        pg.evaluate("paintJob({running:false,done:0,total:0}, 0)")
        browserpool.settled(pg)
        before = pg.evaluate(
            "$('pageTools').getBoundingClientRect().left")
        pg.evaluate("paintJob({running:false,done:0,total:0,error:%r}, 0)"
                    % LONG)
        browserpool.settled(pg)
        assert pg.evaluate(
            "$('pageTools').getBoundingClientRect().left") == before
    _bar(check)


# ------------------------------------------------------------ and it is split

def test_what_the_bar_says_is_not_tangled_up_with_when_it_is_asked():
    """`paintJob` takes the job and paints it. `poll` decides when to ask."""
    js = (PKG / "static" / "js" / "pipeline.js").read_text("utf-8")
    assert "function paintJob(j, pct)" in js
    body = js.split("function paintJob(j, pct)", 1)[1].split("\nfunction ", 1)[0]
    assert "setTimeout" not in body, "timing does not belong in the painter"
    assert "api(" not in body and "fetch(" not in body
