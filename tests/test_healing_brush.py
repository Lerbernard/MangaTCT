"""The healing brush — one of them, and it redraws.

This file used to test the LOCAL healing brush: a PatchMatch-style per-patch
fill blended in the gradient domain, with a three-way trial that trusted the
spot to whichever of `shift`, `patch` and `smooth` rebuilt a band around it
closest to the page. It was built to lee's own brief, *"look only to see how
the photohop conetnt aware healing brush works and make our healing brushh
works as close as posible"*, and it measured well: mean error 40.9 → 36.1 over
96 random spots on eight real chapter pages, better on 47 and worse on 5.

**It is gone.** lee, having used it on his own pages: *"remoev teh regualr
healing brush, its ass"*.

The measurement was not wrong; it was answering the wrong question. All three
of those fills can only MOVE texture that is already somewhere nearby, and the
spots left after the Clean step has run are exactly the ones where what should
be underneath was never on the page at all — a scrap of a face behind a sound
effect, a line of the drawing that only ever existed under the Japanese. A
brush that cannot invent has nothing to offer there, however faithfully it
copies. The AI one redraws, so it is the brush.

The tests here are rewritten rather than deleted, because the requirement did
not go away — it reversed, and what has to hold now is the opposite of what
held before:

* nothing can reach the local fill any more, in the library or in the endpoint;
* there is one healing brush on the toolbar, not two;
* the brush never quietly falls back to the fill lee rejected — a cleaner that
  is not set up SAYS so; and
* `shift_fill` stays, because it was never the brush. It is the Clean step's
  own offline fill, and every page that does not reach a model still uses it.
"""
import inspect
import re
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import editor, inpaint
from scratch import scratch
from where import PKG

STATIC = PKG / "static"


def _heal_endpoint() -> str:
    """The body of the /heal branch, comments and all."""
    src = inspect.getsource(editor.Handler.do_POST)
    cut = src[src.index('r"/api/page/(\\d+)/heal"'):]
    return cut[:cut.index('r"/api/page/(\\d+)/rename"')]


# ------------------------------------------------------------ the fill is gone

def test_the_local_fill_is_not_in_the_library():
    """`heal_spot` and the PatchMatch fill under it were ~460 lines that only
    the brush ever called. A brush nobody wants leaves dead code behind it, and
    dead code is the version that comes back."""
    assert not hasattr(inpaint, "heal_spot")
    assert not hasattr(inpaint, "content_heal")
    for gone in ("_heal_candidates", "_poisson_into", "HEAL_PATCH",
                 "HEAL_CANDS", "HEAL_PASSES", "HEAL_BIG_PX", "HEAL_TRIAL_PX"):
        assert not hasattr(inpaint, gone), gone


def test_the_cleaners_own_fill_is_untouched():
    """`shift_fill` was never the healing brush. It is what the Clean step
    uses on every page that does not go to a model, and taking it out with the
    brush would have quietly turned off offline cleaning."""
    assert hasattr(inpaint, "shift_fill")
    img = np.full((90, 90, 3), 255, np.uint8)
    for k in range(0, 90, 6):
        cv2.line(img, (0, k), (90, k), (150, 150, 150), 1)
    m = np.zeros((90, 90), np.uint8)
    cv2.circle(m, (45, 45), 10, 255, -1)
    out = inpaint.shift_fill(img, m)
    assert out.shape == img.shape
    # real pixels copied in, not a grey smear: the tone survives
    assert out[38:52, 38:52].std() > 8


def test_nothing_in_the_app_still_calls_it():
    """A leftover call is the disliked brush coming back under the other
    one's name."""
    root = PKG
    for f in sorted(root.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.strip().startswith("#"))
        assert "heal_spot(" not in code, f
        assert "content_heal(" not in code, f


# --------------------------------------------------------- one brush, not two

def test_the_toolbar_offers_one_healing_brush():
    js = (STATIC / "js" / "toolbar.js").read_text(encoding="utf-8")
    tools = re.findall(r"name:'([^']*[Hh]ealing[^']*)'", js)
    assert tools == ["Healing brush"], tools


def test_there_is_no_second_switch_left_behind():
    """`healAi` said WHICH of the two was armed. With one brush it says
    nothing, and a flag that says nothing is a flag something will read."""
    for name in ("paint.js", "toolbar.js", "core.js", "picker.js",
                 "panels.js", "select.js"):
        js = (STATIC / "js" / name).read_text(encoding="utf-8")
        assert "healAi" not in js, name
        assert "toggleHealAi" not in js, name


def test_the_brush_still_arms_and_disarms_like_every_other_tool():
    js = (STATIC / "js" / "paint.js").read_text(encoding="utf-8")
    body = js.split("function toggleHeal(on){")[1].split("\n}")[0]
    assert "disarmTools('heal')" in body, body
    assert "paintToolUI()" in body, body
    core = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
    assert "toggleHeal(false)" in core, "disarmTools no longer puts it away"


def test_the_icon_is_the_plaster_with_the_sparkle():
    """The two brushes had two icons. The one that survives is the AI one —
    the plaster with the sparkle that marks every other AI control here."""
    js = (STATIC / "js" / "toolbar.js").read_text(encoding="utf-8")
    assert "icon:'healai'" in js
    assert re.search(r"^\s*heal:'", js, re.M) is None, "the old icon is still defined"


# ------------------------------------------------- and it never quietly falls back

def test_the_endpoint_asks_the_ai_cleaner_and_nothing_else():
    code = _heal_endpoint()
    body = "\n".join(ln for ln in code.splitlines()
                     if not ln.strip().startswith("#"))
    assert "_make_cleaner(p, strict=True)" in body
    assert "heal_spot" not in body
    assert "INPAINT_TELEA" not in body


def test_with_no_cleaner_set_up_it_says_so_rather_than_healing():
    """The old endpoint fell through to the local fill whenever the cleaner
    was missing or refused, and labelled the result the same way. lee ran a
    placeholder token for days without the app ever saying the AI had not
    run once."""
    import json
    import shutil
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    from mangatl.project import Project

    root = scratch("_tmp_heal_off")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((80, 80, 3), 240, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.settings["ai_clean"] = "off"
    p.save()

    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        import base64
        m = np.zeros((80, 80), np.uint8)
        cv2.circle(m, (40, 40), 9, 255, -1)
        enc = lambda a: "data:image/png;base64," + base64.b64encode(
            cv2.imencode(".png", a)[1].tobytes()).decode()
        req = urllib.request.Request(
            base + "/api/page/0/heal",
            data=json.dumps({"image": enc(img), "mask": enc(m)}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.loads(r.read())
        except urllib.error.HTTPError as e:
            j = json.loads(e.read())
        assert j.get("error"), j
        assert "patch" not in j, "it healed anyway"
        # ...and it says WHERE to turn it on. "The AI cleaner did not answer"
        # is the other failure — a cleaner that is set up and refusing — and
        # sending that here would have lee looking at an endpoint he never
        # configured.
        assert "Settings" in j["error"], j["error"]
        assert "did not answer" not in j["error"], j["error"]
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def test_the_reply_no_longer_has_to_say_which_brush_ran():
    """`how` existed to tell the two brushes apart, and `warn` existed because
    one could silently become the other. With one brush that cannot happen —
    the answer is a patch or it is an error."""
    body = "\n".join(ln for ln in _heal_endpoint().splitlines()
                     if not ln.strip().startswith("#"))
    assert '"how": "ai"' in body
    assert '"via"' not in body, "the local method's log field is still sent"
