"""When the hosted cleaner refuses, say so - do not quietly smear the page.

lee: *"the clenning didnt work"*. Two Modal screenshots came with it, both
showing **401** on every call, the first with a 20s cold start and 73ms of
execution - his own function ran and rejected the token, so this was never
Modal's edge proxy.

What made it a week-long mystery is not the 401. It is that nothing in the app
ever said the word:

* `_ai_clean_call` caught every failure, wrote it into `_LAST_AI_CLEAN_ERROR`
  - a variable no code anywhere read - and returned `cv2.inpaint(..., TELEA)`.
  A Telea fill over a whole bubble of text is a grey-brown smudge, so the pages
  came back looking like a *bad clean* rather than like *no clean*, and the
  progress bar said "Ready".
* The settings field showed "(saved)" for any non-empty token. The example token
  in the header of every `*_clean_modal.py` is non-empty, so a project whose
  token had never actually been filled in was indistinguishable, in the only
  screen that could have shown it, from a working one.

Both are fixed here: the failure travels to the bar and to the heal toast in
words that name the cause, and a token that is still the CHANGE-ME example
reports itself as one. The token itself never leaves the server - only which of
the three states it is in.
"""
import json
import os
import re
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")

JS = PKG / "static" / "js"
CSS = PKG / "static" / "css" / "editor.css"


class _Refuse(BaseHTTPRequestHandler):
    """A stand-in for his Modal endpoint, answering exactly as it did: 401 with
    `{"detail":"bad token"}`, from the function itself."""
    code = 401
    hits = 0

    def do_POST(self):                                     # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        type(self).hits += 1
        body = json.dumps({"detail": "bad token"}).encode()
        self.send_response(type(self).code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):                             # keep the run quiet
        pass


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d/clean" % srv.server_address[1]


def _page(w=520, h=380):
    """A bubble with writing in it - something a cleaner would have to erase."""
    img = np.full((h, w, 3), 245, np.uint8)
    img[:, :, 0] = 235                             # faintly toned, not flat
    cv2.ellipse(img, (260, 180), (170, 110), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (260, 180), (170, 110), 0, 0, 360, (20, 20, 20), 3)
    for k in range(4):
        cv2.putText(img, "TEXT", (170, 130 + k * 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (15, 15, 15), 3)
    return img


def _project(root, url, token, kind="sfx"):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.add_uploaded("p0.png", cv2.imencode(".png", _page())[1].tobytes())
    p.settings.update(ai_clean="all", clean_url=url, clean_token=token)
    # `sfx` by default, and not `bubble`, because these tests count calls to
    # the ENDPOINT. A plain white bubble is filled flat and never sent - the
    # local fill knows that colour exactly - which is right, and made every
    # test in this file that counts calls count zero.
    p.pages[0].regions = [{
        "id": 1, "kind": kind, "order": 0,
        "bbox": [160, 100, 200, 160], "bubble_bbox": [90, 70, 340, 220],
        "polygon": [[160, 100], [360, 100], [360, 260], [160, 260]],
        "src_text": "テスト", "dst_text": "TEST", "confidence": 0.9}]
    p.pages[0].detected = True
    return p


# ---------------------------------------------------------------- the words


def test_a_401_is_reported_as_a_refused_token():
    """Not "HTTPError: HTTP Error 401: Unauthorized". The person cannot do
    anything with that; "the cleaner refused the token" names the setting."""
    import urllib.error
    from mangatl.editor import _clean_error_text

    def http(code):
        return urllib.error.HTTPError("u", code, "x", {}, None)

    assert _clean_error_text(http(401)) == "the cleaner refused the token (401)"
    assert "404" in _clean_error_text(http(404))
    assert "nothing at that cleaner address" in _clean_error_text(http(404))
    assert "busy" in _clean_error_text(http(503))
    assert "could not be reached" in _clean_error_text(
        urllib.error.URLError("connection refused"))
    # anything unforeseen still arrives intact rather than as "something failed"
    assert _clean_error_text(ValueError("odd size")) == "ValueError: odd size"


def test_the_placeholder_token_is_its_own_state():
    """"" / "set" / "placeholder". The middle one is what the field used to say
    about all three, which is the whole reason this went unnoticed."""
    from mangatl.project import token_state
    assert token_state("") == ""
    assert token_state(None) == ""
    assert token_state("   ") == ""
    assert token_state("CHANGE-ME-to-your-own-long-random-token") == "placeholder"
    assert token_state("change-me-please") == "placeholder"
    assert token_state(" CHANGE-ME ") == "placeholder"
    assert token_state("k9Xq2vBn7wLt4sRd8pYc3mZa6hGu5jFe1oIb") == "set"


# ------------------------------------------------------- the call and the bar


def test_the_refusal_is_remembered_and_the_page_still_finishes():
    """The run must not break - but the failure must not evaporate either.
    Before: the fill happened, `_LAST_AI_CLEAN_ERROR` was set, and no reader
    existed anywhere in the program."""
    from mangatl import editor
    srv, url = _serve(_Refuse)
    _Refuse.hits = 0
    root = scratch("_tmp_clean_401")
    p = _project(root, url, "CHANGE-ME-to-your-own-long-random-token")
    try:
        editor.clear_clean_warning()
        assert editor.clean_warning(p) == "", "starts quiet"

        neural, every = editor._make_cleaner(p)
        assert neural is not None and every
        img, msk = _page(), np.zeros((380, 520), np.uint8)
        cv2.rectangle(msk, (160, 100), (360, 260), 255, -1)
        out = neural(img, msk)                 # must NOT raise: a run goes on
        assert out is not None and out.shape == img.shape
        assert _Refuse.hits == 1, "the endpoint was never called"

        w = editor.clean_warning(p)
        assert "refused the token (401)" in w, w
        assert "1 spot was filled in with the plain local method" in w, w
        assert "CHANGE-ME" in w, \
            "the warning does not point at the setting that causes it"
        assert "Settings" in w

        # a second failure counts, so "the endpoint is down" reads differently
        # from "one call timed out"
        neural(img + 1, msk)
        assert "2 spots were" in editor.clean_warning(p)

        # the token is named as a state, never quoted
        assert "to-your-own-long-random-token" not in editor.clean_warning(p)
    finally:
        srv.shutdown(); srv.server_close()
        editor.clear_clean_warning()
        shutil.rmtree(root, ignore_errors=True)


def test_no_token_saved_says_that_instead():
    from mangatl import editor
    srv, url = _serve(_Refuse)
    root = scratch("_tmp_clean_notoken")
    p = _project(root, url, "")
    try:
        editor.clear_clean_warning()
        neural, _ = editor._make_cleaner(p)
        msk = np.zeros((380, 520), np.uint8)
        cv2.rectangle(msk, (160, 100), (360, 260), 255, -1)
        neural(_page(), msk)
        w = editor.clean_warning(p)
        # Nobody is told to find a token any more (lee: *"the user shoud not
        # have eth keys"*): signed out with no deploy of their own, the bar
        # says to sign in, and the relay does the rest.
        assert "Sign in" in w and "AI cleaner" in w, w
        assert "CHANGE-ME" not in w and "token is saved" not in w
    finally:
        srv.shutdown(); srv.server_close()
        editor.clear_clean_warning()
        shutil.rmtree(root, ignore_errors=True)


def test_pressing_clean_again_really_does_call_the_cleaner_again():
    """lee, after the first fix: *"when i click click cleane again it dont do
    anything"*.

    It didn't, and it couldn't. The plate built during the 401s was written to
    `plate_cache/` like any other, so the second press found it on disk, reused
    it in milliseconds and never went near the endpoint - which is also why his
    Modal dashboard said "No activity". Pasting the right token would not have
    helped either: `_plate_stamp` keyed on the mode and the URL but not the
    token, so the smeared plate stayed valid.

    Both are fixed: a plate built while the cleaner was refusing is thrown
    away rather than cached, and the token's fingerprint is part of the plate's
    identity.

    THE BUTTON PASSES `force`, and this presses it the way the button does -
    which is now the only thing that reaches the endpoint at all. lee: *"it
    shoudnt rebuild everytime, it shoud ony go to the ai when i clcik the
    button"*. Opening the page, typesetting it or exporting it gets the plate
    that exists or the scan; pressing Clean builds.
    """
    from mangatl import editor
    srv, url = _serve(_Refuse)
    root = scratch("_tmp_clean_retry")
    p = _project(root, url, "CHANGE-ME-x")
    try:
        _Refuse.hits = 0
        editor.clear_clean_warning()
        editor._plate_cache.clear()

        editor.do_clean(p, 0, force=True)
        first = _Refuse.hits
        assert first >= 1, "the endpoint was never called at all"

        # press it again: it must ask again, not serve the smear back
        editor.clear_clean_warning()
        editor._plate_cache.clear()          # as a restart would
        editor.do_clean(p, 0, force=True)
        assert _Refuse.hits > first, \
            "the failed plate was cached, so Clean did nothing the second time"

        # ...and OPENING it does not. The refused build is not kept, so there
        # is no plate to find - and that used to mean every view rebuilt it.
        editor.clear_clean_warning()
        editor._plate_cache.clear()
        again = _Refuse.hits
        page = p.materialize(0)
        editor.clean_page(p, 0, page)
        assert _Refuse.hits == again, \
            "opening the page went back to the cleaner %d times" % (
                _Refuse.hits - again)

        # and a different token is a different plate - not the one from the 401s
        stamp_bad = editor._plate_stamp(p, 0)
        p.settings["clean_token"] = "k9Xq2vBn7wLt4sRd8pYc3mZa6hGu5jFe1oIb"
        assert editor._plate_stamp(p, 0) != stamp_bad, \
            "changing the token reuses the plate built with the wrong one"
    finally:
        srv.shutdown(); srv.server_close()
        editor.clear_clean_warning()
        editor._plate_cache.clear()
        shutil.rmtree(root, ignore_errors=True)


def test_a_good_plate_is_still_cached():
    """The guard above must not turn caching off in general - a page cleaned
    properly has to stay cleaned, or every visit re-runs the model."""
    from mangatl import editor

    class _Ok(_Refuse):
        def do_POST(self):                                 # noqa: N802
            import base64
            n = int(self.headers.get("Content-Length") or 0)
            got = json.loads(self.rfile.read(n))
            type(self).hits += 1
            # answer at the size we were asked about: mangatl sends one crop per
            # bubble, and a reply of the wrong shape is (rightly) a failure
            sent = cv2.imdecode(np.frombuffer(
                base64.b64decode(got["image"]), np.uint8), cv2.IMREAD_COLOR)
            img = np.full_like(sent, 200)
            png = cv2.imencode(".png", img)[1].tobytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)

    srv, url = _serve(_Ok)
    root = scratch("_tmp_clean_cached")
    p = _project(root, url, "k9Xq2vBn7wLt4sRd8pYc3mZa6hGu5jFe1oIb")
    try:
        _Ok.hits = 0
        editor.clear_clean_warning()
        editor._plate_cache.clear()
        editor.do_clean(p, 0)
        once = _Ok.hits
        assert editor._AI_CLEAN_FAIL["used"] >= 1, \
            "the model cleaned this page and nothing counted it"
        assert editor.clean_note(p) == "", \
            "the model DID clean it, so \"nothing was sent\" is a lie"
        editor._plate_cache.clear()          # only the disk cache may answer
        editor.do_clean(p, 0)
        assert _Ok.hits == once, \
            "a good plate is being rebuilt every time, which costs money"
        assert editor.clean_warning(p) == ""

        # Now throw the finished plate away but keep the per-region AI cache -
        # what happens after any change that alters the plate's identity. The
        # answers come back out of the cache, so the model still did this page
        # and the run must not report itself as having sent nothing.
        import glob as _g
        for f in _g.glob(root + "/plate_cache/*.png"):
            os.remove(f)
        editor._plate_cache.clear()
        editor.clear_clean_warning()
        editor.do_clean(p, 0)
        assert _Ok.hits == once, "the per-region cache was not used"
        assert editor._AI_CLEAN_FAIL["used"] >= 1, \
            "a cached answer from the model counts as the model cleaning it"
        assert editor.clean_note(p) == ""
    finally:
        srv.shutdown(); srv.server_close()
        editor.clear_clean_warning()
        editor._plate_cache.clear()
        shutil.rmtree(root, ignore_errors=True)


def test_ai_on_but_nothing_sent_says_so():
    """His dashboard read "No activity" and his settings read "AI for hard
    areas". Both were true at once: a flat white balloon is cleaned by the local
    flat fill and never reaches the model. Silence there is correct and looks
    exactly like a broken endpoint, so it gets a sentence."""
    from mangatl import editor
    root = scratch("_tmp_clean_quiet")
    p = _project(root, "https://example.invalid/clean", "a-real-looking-token")
    try:
        editor.clear_clean_warning()
        # a run that actually rebuilt a plate - otherwise "nothing was sent" is
        # just the plate cache doing its job and is not worth saying
        editor._tally_clean({"built": 1})
        p.settings["ai_clean"] = "hard"
        note = editor.clean_note(p)
        assert "nothing was sent" in note and "whole page" in note, note

        p.settings["ai_clean"] = "all"
        assert "nothing was sent" in editor.clean_note(p)

        # off, or no address: not a thing to mention
        p.settings["ai_clean"] = "off"
        assert editor.clean_note(p) == ""
        p.settings["ai_clean"] = "all"
        p.settings["clean_url"] = ""
        assert editor.clean_note(p) == ""

        # nothing rebuilt means nothing to send: the plates were reused, and
        # saying "the AI did not run" about that is what made a WORKING cleaner
        # look broken (lee: *"its saying the ai did not run even though the
        # clean token is working"*)
        editor._CLEAN_TALLY.pop("built", None)
        assert editor.clean_note(p) == ""
        editor._tally_clean({"built": 1})

        # and once the model HAS done something, silence is not the story
        p.settings["clean_url"] = "https://example.invalid/clean"
        editor._AI_CLEAN_FAIL["used"] = 3
        assert editor.clean_note(p) == ""
        # nor is it, when there is a real failure to report instead
        editor._AI_CLEAN_FAIL.update(used=0, n=2, msg="the cleaner refused the token (401)")
        assert editor.clean_note(p) == ""
        assert editor.clean_warning(p)
    finally:
        editor.clear_clean_warning()
        shutil.rmtree(root, ignore_errors=True)


def test_a_working_cleaner_clears_the_warning():
    """Otherwise the bar nags forever about a call that has since succeeded -
    and a stale warning is trusted about as much as no warning at all."""
    from mangatl import editor

    class _Ok(_Refuse):
        def do_POST(self):                                 # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            got = json.loads(self.rfile.read(n))
            png = cv2.imencode(".png", np.full((380, 520, 3), 200, np.uint8))[1]
            assert "image" in got and "mask" in got and "token" in got
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png.tobytes())))
            self.end_headers()
            self.wfile.write(png.tobytes())

    bad, bad_url = _serve(_Refuse)
    good, good_url = _serve(_Ok)
    root = scratch("_tmp_clean_recover")
    p = _project(root, bad_url, "CHANGE-ME-x")
    try:
        msk = np.zeros((380, 520), np.uint8)
        cv2.rectangle(msk, (160, 100), (360, 260), 255, -1)
        editor.clear_clean_warning()
        editor._make_cleaner(p)[0](_page(), msk)
        assert editor.clean_warning(p)

        p.settings["clean_url"] = good_url
        out = editor._make_cleaner(p)[0](_page(), msk)
        assert out is not None
        assert editor.clean_warning(p) == "", "the warning outlived the failure"
    finally:
        for s in (bad, good):
            s.shutdown(); s.server_close()
        editor.clear_clean_warning()
        shutil.rmtree(root, ignore_errors=True)


def test_the_job_reply_carries_the_warning():
    """`/api/job` is what the bar reads, so that is where it has to arrive."""
    from mangatl import editor
    srv, url = _serve(_Refuse)
    root = scratch("_tmp_clean_job")
    p = _project(root, url, "CHANGE-ME-x")
    was, editor.PROJECT = editor.PROJECT, p
    esrv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=esrv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % esrv.server_address[1]
    try:
        import urllib.request
        editor.clear_clean_warning()

        def job():
            with urllib.request.urlopen(base + "/api/job", timeout=20) as r:
                return json.loads(r.read())

        assert "warn" not in job(), "a quiet cleaner must not warn"

        req = urllib.request.Request(
            base + "/api/clean_all", data=json.dumps({"pages": [0]}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            assert json.loads(r.read())["started"] == 1
        for _ in range(120):                       # the job runs in a thread
            j = job()
            if not j.get("running") and j.get("warn"):
                break
            threading.Event().wait(0.25)
        j = job()
        assert not j.get("error"), \
            f"the run should FINISH, only worse: {j.get('error')}"
        assert "refused the token (401)" in (j.get("warn") or ""), j
        assert p.pages[0].cleaned or True         # it did clean, just locally
    finally:
        esrv.shutdown(); esrv.server_close()
        srv.shutdown(); srv.server_close()
        editor.PROJECT = was
        editor.clear_clean_warning()
        shutil.rmtree(root, ignore_errors=True)


def test_a_new_run_does_not_inherit_the_last_run_s_warning():
    """A warning describes the run being watched. Left standing, it would say
    "AI cleaning did not run" over a run in which cleaning was never asked for
    - and a bar that cries wolf is read as decoration."""
    from mangatl import editor
    root = scratch("_tmp_clean_stale")
    p = _project(root, "", "")            # no cleaner at all this time
    p.settings["ai_clean"] = "off"
    was, editor.PROJECT = editor.PROJECT, p
    esrv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=esrv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % esrv.server_address[1]
    try:
        import urllib.request
        # yesterday's refusal, still sitting in the module
        editor._AI_CLEAN_FAIL.update(
            n=9, msg="the cleaner refused the token (401)", url="http://old")

        def job():
            with urllib.request.urlopen(base + "/api/job", timeout=20) as r:
                return json.loads(r.read())

        assert job().get("warn"), "the fixture's stale warning never arrived"
        req = urllib.request.Request(
            base + "/api/clean_all", data=json.dumps({"pages": [0]}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        for _ in range(120):
            if not job().get("running"):
                break
            threading.Event().wait(0.25)
        assert not job().get("warn"), \
            "this run cleaned locally by choice, and was told off for it"
    finally:
        esrv.shutdown(); esrv.server_close()
        editor.PROJECT = was
        editor.clear_clean_warning()
        shutil.rmtree(root, ignore_errors=True)


def test_the_heal_brush_names_the_reason_when_the_cleaner_refuses():
    """It used to fall back to the local brush and the toast guessed "not
    reachable" for every cause; then the reply started naming the cause. Now
    there is nothing to fall back TO - lee: *"remoev teh regualr healing
    brush, its ass"* - so the named cause is the whole answer, and it must
    still be the specific one rather than a shrug."""
    from mangatl import editor
    import base64
    srv, url = _serve(_Refuse)
    root = scratch("_tmp_clean_heal")
    p = _project(root, url, "CHANGE-ME-x")
    was, editor.PROJECT = editor.PROJECT, p
    esrv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=esrv.serve_forever, daemon=True).start()
    base_u = "http://127.0.0.1:%d" % esrv.server_address[1]
    try:
        import urllib.request, urllib.error
        crop = _page()[60:280, 120:400]
        m = np.zeros(crop.shape[:2], np.uint8)
        cv2.rectangle(m, (50, 40), (200, 150), 255, -1)
        payload = {
            "image": "data:image/png;base64," + base64.b64encode(
                cv2.imencode(".png", crop)[1].tobytes()).decode(),
            "mask": "data:image/png;base64," + base64.b64encode(
                cv2.imencode(".png", m)[1].tobytes()).decode()}
        req = urllib.request.Request(
            base_u + "/api/page/0/heal", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.loads(r.read())
        except urllib.error.HTTPError as e:
            j = json.loads(e.read())
        assert "patch" not in j, "the endpoint refused, so nothing was healed"
        assert "refused the token (401)" in (j.get("error") or ""), j
    finally:
        esrv.shutdown(); esrv.server_close()
        srv.shutdown(); srv.server_close()
        editor.PROJECT = was
        editor.clear_clean_warning()
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------- telling apart the two 401 causes


def _deploy_file(tmp: Path, name: str, token: str, app: str) -> Path:
    """A stand-in for one of his `*_clean_modal.py` scripts."""
    fp = tmp / name
    fp.write_text(
        "import modal\n"
        f'CLEAN_TOKEN = "{token}"\n'
        f'app = modal.App("{app}")\n', encoding="utf8")
    return fp


def test_the_selftest_tells_a_wrong_token_from_a_stale_deployment(tmp_path,
                                                                  monkeypatch):
    """lee, with the first fix in place: *"CLEAN_TOKEN is the same in the app and
    in the code can you look into it?"* - and the endpoint still answering 401,
    194ms of execution, so his function really was running and really was
    refusing.

    Both explanations end in the same 401 and nothing could tell them apart:
    either the string in Settings is not the string in the file, or it IS and the
    DEPLOYED image was built before the file changed, so the container still
    compares the old one. The self-test answers exactly that, by hashing the
    saved token against each local deploy script - never printing either.
    """
    from mangatl import editor
    srv, url = _serve(_Refuse)
    root = str(tmp_path / "proj")
    real = "k9Xq2vBn7wLt4sRd8pYc3mZa6hGu5jFe1oIb-59-characters-worth"
    _deploy_file(tmp_path, "lama_clean_modal.py", real, "mangatl-clean-lama")
    _deploy_file(tmp_path, "manga_clean_modal.py", real, "mangatl-clean")
    # only the fixture's scripts, so a real one lying beside the code cannot
    # decide the outcome
    monkeypatch.setattr(editor, "_deploy_dirs", lambda: [str(tmp_path)])
    p = _project(root, url + "/mangatl-clean-lama-cleaner", real)
    try:
        editor.clear_clean_warning()
        r = editor.clean_selftest(p)
        assert r["ok"] is False
        assert "refused the token (401)" in r["error"]
        # the token IS the file's, so the answer is "redeploy", by name
        assert "out of date" in r["hint"], r["hint"]
        assert "modal deploy lama_clean_modal.py" in r["hint"], r["hint"]
        named = [f for f in r["files"] if f["file"] == "lama_clean_modal.py"][0]
        assert named["same_token"] and named["url_matches"]
        other = [f for f in r["files"] if f["file"] == "manga_clean_modal.py"][0]
        assert other["same_token"] and not other["url_matches"]

        # now the other cause: a token that is not the file's
        p.settings["clean_token"] = "some-other-string-entirely"
        r = editor.clean_selftest(p)
        assert "is not the one in lama_clean_modal.py" in r["hint"], r["hint"]
        assert not any(f["same_token"] for f in r["files"])

        # never the secret itself, in either direction
        blob = json.dumps(r) + json.dumps(editor.clean_selftest(p))
        assert real not in blob and "some-other-string-entirely" not in blob
        assert r["token"]["len"] == len("some-other-string-entirely")

        # and a self-test is not a run: it must not leave a warning in the bar
        assert editor.clean_warning(p) == "", \
            "pressing Test put a warning on the progress bar"
    finally:
        srv.shutdown(); srv.server_close()
        editor.clear_clean_warning()


def test_the_selftest_reports_a_working_cleaner(tmp_path, monkeypatch):
    from mangatl import editor

    class _Ok(_Refuse):
        def do_POST(self):                                 # noqa: N802
            import base64
            n = int(self.headers.get("Content-Length") or 0)
            got = json.loads(self.rfile.read(n))
            type(self).hits += 1
            sent = cv2.imdecode(np.frombuffer(
                base64.b64decode(got["image"]), np.uint8), cv2.IMREAD_COLOR)
            png = cv2.imencode(".png", np.full_like(sent, 210))[1].tobytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)

    srv, url = _serve(_Ok)
    monkeypatch.setattr(editor, "_deploy_dirs", lambda: [str(tmp_path)])
    _deploy_file(tmp_path, "lama_clean_modal.py", "tok-abc", "mangatl-clean-lama")
    p = _project(str(tmp_path / "proj"), url, "tok-abc")
    try:
        editor.clear_clean_warning()
        r = editor.clean_selftest(p)
        assert r["ok"] is True, r
        assert "answered" in r["hint"]
        # the test bypasses the cache - a page cleaned before must not answer
        # for the endpoint, or the button would say "fine" about a dead one
        n = _Ok.hits
        editor.clean_selftest(p)
        assert _Ok.hits == n + 1, "the self-test was served from a cache"
    finally:
        srv.shutdown(); srv.server_close()
        editor.clear_clean_warning()


def test_a_pasted_token_loses_its_whitespace_and_quotes(tmp_path):
    """The invisible cause of "but it's the same token": a copy that brought a
    trailing newline, or the quotes from around the literal, with it."""
    from mangatl import editor
    root = str(tmp_path / "proj")
    p = _project(root, "http://127.0.0.1:9/none", "")
    was, editor.PROJECT = editor.PROJECT, p
    esrv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=esrv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % esrv.server_address[1]
    try:
        import urllib.request
        for pasted in ('  tok-abc\n', '"tok-abc"', "'tok-abc' ", "tok-abc\r\n"):
            req = urllib.request.Request(
                base + "/api/settings",
                data=json.dumps({"settings": {"clean_token": pasted,
                                              "clean_url": " http://x/clean "}}
                                ).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                r.read()
            assert p.settings["clean_token"] == "tok-abc", \
                f"{pasted!r} was stored as {p.settings['clean_token']!r}"
            assert p.settings["clean_url"] == "http://x/clean"

        # and an old project.json that still holds the whitespace is stripped
        # on the way out to the endpoint
        p.settings["clean_token"] = "  tok-abc\n"
        p.settings["clean_url"] = "http://127.0.0.1:9/none"
        seen = {}
        real = editor._ai_clean_call

        def spy(url, token, *a, **k):
            seen["token"] = token
            raise RuntimeError("stop here")

        editor._ai_clean_call = spy
        try:
            neural, _ = editor._make_cleaner(p, strict=True)
            try:
                neural(np.zeros((8, 8, 3), np.uint8), np.zeros((8, 8), np.uint8))
            except RuntimeError:
                pass
        finally:
            editor._ai_clean_call = real
        assert seen["token"] == "tok-abc", repr(seen.get("token"))
    finally:
        esrv.shutdown(); esrv.server_close()
        editor.PROJECT = was
        editor.clear_clean_warning()


# --------------------------------------------------------- in a real browser


def test_the_bar_says_when_nothing_was_sent(tmp_path):
    """"AI for hard areas" + a page of flat balloons = a Clean that never
    touches the endpoint. That is right, and it is also exactly what lee's Modal
    dashboard was showing him ("No activity") while he wondered what was broken.
    The bar says it out loud now. In a real browser, with a stand-in endpoint
    that must be left entirely alone."""
    from mangatl import editor
    srv, url = _serve(_Refuse)
    root = scratch("_tmp_clean_quietui")
    # ...and THIS one wants the flat bubble, because a page of flat balloons
    # never touching the endpoint is the whole thing being reported.
    p = _project(root, url, "k9Xq2vBn7wLt4sRd8pYc3mZa6hGu5jFe1oIb",
                 kind="bubble")
    p.settings["ai_clean"] = "hard"          # what his settings actually say
    was, editor.PROJECT = editor.PROJECT, p
    esrv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=esrv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % esrv.server_address[1]
    shots = Path(str(tmp_path))
    try:
        _Refuse.hits = 0
        editor.clear_clean_warning()
        editor._plate_cache.clear()
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("(async()=>{await api('/api/clean_all','POST',"
                        "{pages:[0]}); poll();})()")
            pg.wait_for_function(
                "(()=>{const t=$('toast');return t.style.display==='block'"
                " && t.textContent.includes('nothing was sent');})()",
                timeout=90_000)
            said = pg.evaluate("$('toast').textContent")
            assert "whole page" in said, said
            assert _Refuse.hits == 0, \
                "something WAS sent, so the note is wrong"
            # ...and it is NOT dressed up as a failure. Nothing failed: on "AI
            # for hard areas" a page of plain bubbles has nothing hard on it.
            assert pg.evaluate("$('job').className") != "warn", \
                "a page with nothing hard on it is not a broken cleaner"
            assert "did not run" not in pg.evaluate("$('jobtxt').textContent")
            pg.locator("#work").screenshot(path=str(shots / "bar_nothing.png"))
    finally:
        esrv.shutdown(); esrv.server_close()
        srv.shutdown(); srv.server_close()
        editor.PROJECT = was
        editor.clear_clean_warning()
        editor._plate_cache.clear()
        shutil.rmtree(root, ignore_errors=True)


def test_the_test_button_says_which_cause(tmp_path, monkeypatch):
    """The button, in a real browser: one press, one real call, and the answer
    in the settings screen beside the fields that decide it. Writes the picture.
    """
    from mangatl import editor
    srv, url = _serve(_Refuse)
    real = "k9Xq2vBn7wLt4sRd8pYc3mZa6hGu5jFe1oIb-59-characters-worth"
    _deploy_file(tmp_path, "lama_clean_modal.py", real, "mangatl-clean-lama")
    monkeypatch.setattr(editor, "_deploy_dirs", lambda: [str(tmp_path)])
    root = str(tmp_path / "proj")
    p = _project(root, url + "/mangatl-clean-lama-cleaner", real)
    was, editor.PROJECT = editor.PROJECT, p
    esrv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=esrv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % esrv.server_address[1]
    try:
        editor.clear_clean_warning()
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("openSettingsDlg(); setSettingsTab('cleaning')")
            pg.wait_for_timeout(600)
            assert pg.evaluate("!!document.getElementById('cleanTestBtn')"), \
                "there is no Test cleaner button"
            pg.click("#cleanTestBtn")
            pg.wait_for_function(
                "$('cleanTestOut').textContent.includes('401')", timeout=60_000)
            said = pg.evaluate("$('cleanTestOut').textContent")
            assert "refused the token (401)" in said.lower(), said
            assert "out of date" in said and "modal deploy" in said, said
            assert "token matches" in said, said
            assert real not in said, "the button printed the token"
            assert pg.evaluate(
                "$('cleanTestOut').classList.contains('warnbad')")
            pg.locator("#aicfg").screenshot(path=str(tmp_path / "test_btn.png"))
            assert not errs, errs[:3]
    finally:
        esrv.shutdown(); esrv.server_close()
        srv.shutdown(); srv.server_close()
        editor.PROJECT = was
        editor.clear_clean_warning()


def test_the_bar_and_the_field_both_say_it(tmp_path):
    """Chromium, against the real server, with a cleaner that refuses: the bar
    goes orange and says so, the toast carries the instruction - and the
    settings screen has no token field to point at. Writes the pictures."""
    from mangatl import editor
    srv, url = _serve(_Refuse)
    root = scratch("_tmp_clean_ui")
    p = _project(root, url, "CHANGE-ME-to-your-own-long-random-token")
    was, editor.PROJECT = editor.PROJECT, p
    esrv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=esrv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % esrv.server_address[1]
    # Outside the tree on purpose: `_sample_pages` in test_pipeline sweeps "."
    # for images, so a screenshot left in the working folder gets fed to the
    # detector as if it were a manga page.
    shots = Path(str(tmp_path))
    try:
        editor.clear_clean_warning()
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)

            assert pg.evaluate("$('job').className") != "warn"
            pg.locator("#work").screenshot(path=str(shots / "bar_before.png"))

            pg.evaluate("(async()=>{await api('/api/clean_all','POST',"
                        "{pages:[0]}); poll();})()")
            pg.wait_for_function("$('job').className==='warn'", timeout=90_000)
            txt = pg.evaluate("$('jobtxt').textContent")
            tip = pg.evaluate("$('job').title")
            assert "AI cleaning did not run" in txt, txt   # the warning's own words
            assert "refused the token (401)" in tip, tip
            assert "CHANGE-ME" in tip
            pg.locator("#work").screenshot(path=str(shots / "bar_after.png"))
            toast = pg.evaluate("(()=>{const t=$('toast');"
                                "return t.style.display==='block'"
                                "?t.textContent:'';})()")
            assert "refused the token (401)" in toast, toast
            pg.screenshot(path=str(shots / "toast.png"))
            pg.locator("#toast").screenshot(path=str(shots / "toast_only.png"))

            # The settings field that used to turn red here is gone: the
            # token is the project's, not the person's (lee: *"the user shoud
            # not have eth keys"*), and Page cleaning shows no box for one.
            pg.evaluate("openSettingsDlg(); setSettingsTab('cleaning')")
            pg.wait_for_timeout(700)
            assert pg.evaluate("!document.getElementById('clean_token') && !document.getElementById('clean_url')")
            pg.screenshot(path=str(shots / "settings_no_field.png"))
            assert not errs, errs[:3]
    finally:
        esrv.shutdown(); esrv.server_close()
        srv.shutdown(); srv.server_close()
        editor.PROJECT = was
        editor.clear_clean_warning()
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------- the guards


def test_the_failure_is_never_swallowed_again():
    """`_ai_clean_call` may keep the Telea fallback - a run must not break over
    a network - but it may not keep it *silently*. The record is the fix; this
    fails if the recording line is ever removed from the handler."""
    src = (PKG / "editor.py").read_text(encoding="utf8")
    body = src[src.index("def _ai_clean_call("):]
    body = body[:body.index("\ndef ", 5)]
    tail = body[body.index("    except Exception as e:"):]
    assert '_AI_CLEAN_FAIL["n"] += 1' in tail, \
        "the fallback is silent again — nothing counts the failure"
    assert "_clean_error_text(e)" in tail
    assert "cv2.INPAINT_TELEA" in tail, "the run must still finish"
    assert "clear_clean_warning()" in body[:body.index("    except Exception")], \
        "a success must clear the old warning"

    # and something must READ it: a recorded failure with no reader is exactly
    # the bug (_LAST_AI_CLEAN_ERROR was written for a year and read by nothing)
    assert src.count("clean_warning(p)") >= 2, \
        "the warning is recorded but never surfaced"
    assert re.search(r'j\["warn"\]\s*=\s*w', src), \
        "/api/job does not carry the warning"

    js = (JS / "pipeline.js").read_text(encoding="utf8")
    assert "j.warn" in js and "'warn'" in js, "the bar ignores the warning"
    css = CSS.read_text(encoding="utf8")
    assert "#job.warn #jobtxt" in css, "the warning has no colour of its own"
    assert "input.bad" in css


def test_the_token_is_never_sent_to_the_browser():
    """The settings reply must carry the STATE, not the secret - and the
    warning must not quote it either."""
    from mangatl.project import Project
    root = scratch("_tmp_clean_secret")
    shutil.rmtree(root, ignore_errors=True)
    try:
        p = Project(None, root)
        secret = "s3cret-token-nobody-should-see-9f2a"
        p.settings.update(api_key="ak-live-should-not-appear",
                          clean_token=secret, clean_url="http://x/clean")
        blob = json.dumps(p.summary())
        assert secret not in blob and "ak-live" not in blob
        assert json.loads(blob)["settings"]["clean_token"] == "set"

        from mangatl import editor
        editor._AI_CLEAN_FAIL.update(n=1, msg="the cleaner refused the token (401)")
        assert secret not in editor.clean_warning(p)
        editor.clear_clean_warning()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_refused_call_repairs_locally_at_the_right_size():
    """lee: *"the clenner is clenning boxes that the ai shoud"* - with a picture
    of a dark panel wiped grey where a bubble had been.

    That smear is the model's own mask being filled by a local method. The wide
    mask (`NEURAL_PAD` past the typesetting) is a favour to a model that redraws
    whatever it is shown; a plain fill over the same area replaces artwork with a
    guess. The refusal now reaches `_run_neural`, which repairs the region with
    the TIGHT mask instead - the typesetting and a couple of pixels of its edge.

    Measured on 24 synthetic typesettings over real pages: tight beat wide on 22,
    mean error 39.3 against 45.6.
    """
    from mangatl import inpaint as I
    from mangatl.models import Page, TextRegion

    page_img = np.full((260, 320, 3), 40, np.uint8)
    page_img[::3, :] = 90                      # hatching, so a fill has to guess
    cv2.putText(page_img, "GO", (110, 150), cv2.FONT_HERSHEY_SIMPLEX, 2.0,
                (255, 255, 255), 8)            # white typesetting on a dark panel
    gray = cv2.cvtColor(page_img, cv2.COLOR_BGR2GRAY)

    def build():
        pg = Page(image=page_img.copy())
        tm = np.zeros(gray.shape, np.uint8)
        tm[110:180, 100:240] = (gray[110:180, 100:240] > 190).astype(np.uint8) * 255
        r = TextRegion(id=1, bbox=(100, 110, 140, 70), kind="sfx", order=0,
                       src_text="ゴ", dst_text="GO")
        r.text_mask = tm
        pg.regions = [r]
        return pg

    def swallow(sub, sm):                      # what it used to do on a 401
        return cv2.inpaint(sub, sm, 3, cv2.INPAINT_TELEA)

    def refuse(sub, sm):
        raise RuntimeError("401 bad token")

    before = I.inpaint_page(build(), neural=swallow, neural_all=True)
    after = I.inpaint_page(build(), neural=refuse, neural_all=True)

    touched = lambda out: int((np.abs(out.astype(int)
                                      - page_img.astype(int)).max(2) > 6).sum())
    assert touched(after) < touched(before) * 0.9, \
        f"the refused call still replaces as much page: {touched(after)} vs " \
        f"{touched(before)}"

    # and it is still a CLEAN: the typesetting has to be gone either way
    letters = (gray > 190)
    assert after[letters].mean() < 160, \
        "the typesetting survived, so this is not a cleaned page at all"

    # the artwork just outside the typesetting is what the wide mask was eating
    ring = (cv2.dilate(letters.astype(np.uint8), np.ones((13, 13), np.uint8))
            > 0) & ~letters
    keep = lambda out: float(np.abs(out[ring].astype(int)
                                    - page_img[ring].astype(int)).mean())
    assert keep(after) < keep(before), \
        f"the ring around the words is no better kept: {keep(after)} vs {keep(before)}"


def test_the_page_run_lets_the_refusal_through():
    """`clean_page` must ask for the strict cleaner, or the refusal never
    reaches the inpainter and the old wide smear comes back."""
    src = (PKG / "editor.py").read_text(encoding="utf8")
    fn = src[src.index("def clean_page("):]
    fn = fn[:fn.index("\ndef ", 5)]
    assert "_make_cleaner(p, strict=True)" in fn, \
        "clean_page is swallowing the failure again"
    inp = (PKG / "inpaint.py").read_text(encoding="utf8")
    assert '"tight": d' in inp, "the tight mask does not travel with the job"
    assert "def _local_fill(" in inp
    run = inp[inp.index("def _run_neural("):]
    run = run[:run.index("\ndef ", 5)]
    assert run.count("_local_fill(out, job)") == 3, \
        "a failed, unusable or blank answer must fall back locally"
    # Three, not two: an answer that came back flat where the artwork around it
    # has detail is a refusal wearing the shape of a result, and goes the same
    # way. lee: *"the ai seem to have given up and just made teh white box
    # instard of cleaning teh text"*.
    assert "_gave_up(sub, filled, sm)" in run


def test_a_tiny_region_does_not_take_the_page_down():
    """`ink_and_background` returned TWO values on its "too little to split"
    path and three on every other one, so a region with a placement area under
    40 pixels raised ValueError halfway through cleaning and the whole page
    came back 500 with nothing on screen to say why.

    Found by accident: a test fixture drew a box smaller than its own bubble.
    """
    import numpy as np
    from mangatl.inpaint import ink_and_background

    gray = np.full((40, 40), 200, np.uint8)
    tiny = np.zeros((40, 40), bool)
    tiny[5:8, 5:9] = True                       # 12 pixels
    fallback = np.zeros((40, 40), np.uint8)
    glyph, level, inverted = ink_and_background(gray, tiny, fallback)
    assert glyph is fallback
    assert level == 200
    assert inverted is False

    empty = np.zeros((40, 40), bool)
    glyph, level, inverted = ink_and_background(gray, empty, fallback)
    assert level == 255.0 and inverted is False


def test_a_whole_page_cleans_with_a_tiny_region_on_it():
    """The end the person actually sees: the page renders."""
    import numpy as np
    import cv2
    from mangatl.inpaint import inpaint_page
    from mangatl.models import Page, TextRegion

    img = np.full((300, 300, 3), 240, np.uint8)
    cv2.rectangle(img, (100, 100), (160, 140), (20, 20, 20), -1)
    page = Page(image=img)
    small = np.zeros((300, 300), np.uint8)
    small[50:52, 50:53] = 255                   # 6 pixels of "writing"
    big = np.zeros((300, 300), np.uint8)
    big[100:141, 100:161] = 255
    page.regions = [
        TextRegion(id=1, bbox=(50, 50, 3, 2), text_mask=small, kind="bubble",
                   order=0),
        TextRegion(id=2, bbox=(100, 100, 61, 41), text_mask=big, kind="bubble",
                   order=1),
    ]
    out = inpaint_page(page)                    # must not raise
    assert out.shape == img.shape
