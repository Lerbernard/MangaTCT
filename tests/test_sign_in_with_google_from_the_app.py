"""Sign in with Google, from the app.

lee: *"sign in / sign up and login with google like in the website"*.

Google's sign-in is a popup on a Google page and it wants a real browser, so
the app does not draw it. Pressing "Continue with Google" in the app asks the
server for a one-time nonce, the server opens the website's own sign-in page
in the system browser with `?app=<port>&state=<nonce>` in its address, and
the page, once the person is in (Google or email), hands the credential to
the app as a form post to `127.0.0.1:<port>/api/account/hand`. The app has
been asking every two seconds whether the hand has come; when it has, the
purse, the Account page and Home all paint as signed in.

What is checked here: the nonce is minted and spent, the wrong page and a
stale nonce are refused, a credential that Google will not turn into a
token leaves nothing on disk, the form post gets an HTML page and a fetch
gets JSON, the site page does the hand when `?app=` is there and does not
when it is not, and the in-app form has the button.
"""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from where import PKG
from mangatl import account, coins, editor
from mangatl.project import Project

JS = (PKG / "static" / "js" / "coins.js").read_text(encoding="utf-8")
SIGNIN = (PKG / "site" / "signin.html").read_text(encoding="utf-8")


@pytest.fixture
def configured(monkeypatch, tmp_path):
    """An installed copy that can talk to a project - and a Google that says
    yes to one refresh token and no to every other."""
    monkeypatch.delenv(coins.TEST_PURSE, raising=False)
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path))
    monkeypatch.setattr(account, "_repo_config",
                        lambda: {"apiKey": "k", "projectId": "proj", "region": "us-central1"})
    account._MEM.clear()
    account._HANDS.clear()

    def post(url, body, token=""):
        if url.startswith(account.REFRESH):
            if body.get("refresh_token") == "good-refresh":
                return {"id_token": "id.tok", "refresh_token": "good-refresh",
                        "user_id": "u1", "expires_in": "3600"}
            raise account._says({"error": {"message": "INVALID_REFRESH_TOKEN"}}, 400)
        if url.endswith("/me"):
            return {"result": {"username": "lee", "coins": 12, "verified": True}}
        raise AssertionError("unexpected call " + url)
    monkeypatch.setattr(account, "_post", post)
    return tmp_path


def _serve(p):
    was, editor.PROJECT = editor.PROJECT, p
    srv = editor.ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, was, "http://127.0.0.1:%d" % srv.server_address[1]


def _stop(srv, was):
    srv.shutdown()
    srv.server_close()
    editor.PROJECT = was


def _json(base, route, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    head = {"Content-Type": "application/json", "Accept": "application/json"}
    head.update(headers or {})
    req = urllib.request.Request(base + route, data, head)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _form(base, route, fields, origin="https://mangatct.com"):
    """What a browser does with the site's hidden form: a top-level post."""
    data = urllib.parse.urlencode(fields).encode()
    head = {"Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml", "Origin": origin}
    req = urllib.request.Request(base + route, data, head)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode("utf8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf8")


# ------------------------------------------------------------------ the nonce

def test_the_nonce_is_minted_for_a_port_and_spent_on_use(configured):
    got = account.begin_handoff(8765)
    assert got["state"] and len(got["state"]) >= 24
    q = urllib.parse.parse_qs(urllib.parse.urlparse(got["url"]).query)
    assert got["url"].startswith(account.SITE + "/signin?")
    assert q["app"] == ["8765"] and q["state"] == [got["state"]] and "new" not in q
    assert account.handoff_state(got["state"]) == {"known": True, "done": False, "who": ""}
    assert account.handoff_state("nope") == {"known": False, "done": False}

    account.finish_handoff(got["state"], "good-refresh", "id.tok", "u1", "lee@x.y",
                           origin="https://mangatct.com")
    assert account.signed_in()
    d = account._read()
    assert d["refreshToken"] == "good-refresh" and d["idToken"] == "id.tok"
    assert d["uid"] == "u1" and d["email"] == "lee@x.y" and d["username"] == "lee"
    st = account.handoff_state(got["state"])
    assert st["done"] is True and st["who"] == "lee@x.y"
    # once
    with pytest.raises(account.AccountError) as e:
        account.finish_handoff(got["state"], "good-refresh", origin="https://mangatct.com")
    assert e.value.code == "used"


def test_making_an_account_opens_the_page_on_its_sign_up_side(configured):
    got = account.begin_handoff(8765, making=True)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(got["url"]).query)
    assert q["new"] == ["1"]


def test_the_wrong_page_and_a_stale_nonce_are_refused(configured, monkeypatch):
    got = account.begin_handoff(8765)
    with pytest.raises(account.AccountError) as e:
        account.finish_handoff(got["state"], "good-refresh", origin="https://evil.example")
    assert e.value.code == "origin" and not account.signed_in()
    # the site's own other names are fine
    assert "https://proj.web.app" in account.hand_origins()
    assert "https://proj.firebaseapp.com" in account.hand_origins()
    # ten minutes and it is gone
    account._HANDS[got["state"]]["at"] -= account.HAND_FOR + 1
    with pytest.raises(account.AccountError) as e:
        account.finish_handoff(got["state"], "good-refresh", origin="https://mangatct.com")
    assert e.value.code == "stale" and not account.signed_in()
    with pytest.raises(account.AccountError) as e:
        account.finish_handoff("", "good-refresh")
    assert e.value.code == "stale"


def test_a_credential_google_refuses_leaves_nothing_behind(configured):
    got = account.begin_handoff(8765)
    with pytest.raises(account.AccountError):
        account.finish_handoff(got["state"], "made-up", origin="https://mangatct.com")
    assert not account.signed_in()
    assert account._read().get("refreshToken", "") == ""
    assert account.handoff_state(got["state"])["done"] is False, "still open to a real one"
    account.finish_handoff(got["state"], "good-refresh", origin="https://mangatct.com")
    assert account.signed_in()


def test_a_bad_hand_does_not_sign_out_whoever_was_in(configured):
    account._keep({"refreshToken": "good-refresh", "idToken": "old", "localId": "u1",
                   "email": "lee@x.y"})
    got = account.begin_handoff(8765)
    with pytest.raises(account.AccountError):
        account.finish_handoff(got["state"], "made-up", origin="https://mangatct.com")
    assert account._read()["refreshToken"] == "good-refresh"


# ------------------------------------------------------------ through the app

def test_the_button_opens_the_browser_and_the_form_post_signs_the_app_in(
        configured, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(editor.webbrowser, "open", lambda u: opened.append(u))
    p = Project(None, str(tmp_path / "out"))
    srv, was, base = _serve(p)
    try:
        port = srv.server_address[1]
        code, got = _json(base, "/api/account", {"do": "google"})
        assert code == 200 and got["ok"] and got["state"] and got["url"]
        assert "app=%d" % port in got["url"], "the page must know where to post"
        for _ in range(50):
            if opened:
                break
            time.sleep(0.05)
        assert opened == [got["url"]], "the system browser, on the site's page"

        # the app is waiting
        code, st = _json(base, "/api/account/hand?state=" + got["state"])
        assert code == 200 and st == {"known": True, "done": False, "who": ""}

        # the page hands it over, as a browser would: a form post, with Origin
        code, page = _form(base, "/api/account/hand",
                           {"state": got["state"], "refreshToken": "good-refresh",
                            "idToken": "id.tok", "uid": "u1", "email": "lee@x.y"})
        assert code == 200 and "<!doctype html>" in page
        assert "signed in as <b>lee</b>" in page and "close this tab" in page

        code, st = _json(base, "/api/account/hand?state=" + got["state"])
        assert st["done"] is True and st["who"] == "lee@x.y"
        assert st["signed_in"] is True and st["balance"] == 12, "the purse, painted at once"
        assert account.signed_in()
    finally:
        _stop(srv, was)


def test_a_form_post_from_elsewhere_gets_a_page_that_says_no(configured, tmp_path):
    p = Project(None, str(tmp_path / "out"))
    srv, was, base = _serve(p)
    try:
        code, got = _json(base, "/api/account", {"do": "google", "open": False})
        code, page = _form(base, "/api/account/hand",
                           {"state": got["state"], "refreshToken": "good-refresh"},
                           origin="https://evil.example")
        assert code == 400 and "did not work" in page and "may not sign the app in" in page
        assert not account.signed_in()
        # a fetch, not a navigation, is answered in JSON
        code, got2 = _json(base, "/api/account/hand",
                           {"state": "nope", "refreshToken": "good-refresh"})
        assert code == 400 and "expired" in got2["error"] and got2["code"] == "stale"
    finally:
        _stop(srv, was)


def test_an_unconfigured_copy_says_so_instead_of_opening_anything(monkeypatch, tmp_path):
    monkeypatch.setattr(account, "_repo_config", lambda: {})
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path))
    account._MEM.clear()
    with pytest.raises(account.AccountError) as e:
        account.begin_handoff(1)
    assert e.value.code == "unconfigured"


# ------------------------------------------------------------------- the site

def test_the_site_page_hands_the_sign_in_to_the_app_when_the_app_sent_it():
    assert 'id="forApp"' in SIGNIN and "hidden" in SIGNIN[SIGNIN.index('id="forApp"') - 40:SIGNIN.index('id="forApp"') + 60]
    assert "q.get('app')" in SIGNIN and "q.get('state')" in SIGNIN
    assert "/^\\d{2,5}$/.test(port)" in SIGNIN, "a port is digits or it is nothing"
    assert "/api/account/hand'" in SIGNIN and "'http://127.0.0.1:' + forApp.port" in SIGNIN
    assert "f.method = 'POST'" in SIGNIN and "f.submit()" in SIGNIN
    for field in ("state", "refreshToken", "idToken", "uid", "email"):
        assert "put('%s'" % field in SIGNIN
    # every way in ends the same way: `arrive`, which hands or goes on
    assert "askName(() => arrive(made.user))" in SIGNIN
    assert "arrive(got.user)" in SIGNIN and "arrive(cred.user)" in SIGNIN
    assert "if (forApp && user) handToApp(user);\n  else location.href = next;" in SIGNIN
    # already signed in: asked, not assumed
    assert "$('useMe').onclick = () => arrive(u);" in SIGNIN
    assert "signOut(auth)" in SIGNIN
    css = (PKG / "site" / "style.css").read_text(encoding="utf-8")
    assert ".forapp{" in css


def test_the_app_form_has_the_google_button_like_the_website():
    body = JS[JS.index("function walletSignIn("):]
    assert 'class="gbtn" onclick="walletGoogle(' in body
    assert "Continue with Google" in body and "Sign up with Google" in body
    assert "or with an email" in body
    assert "function walletGoogle(" in JS and "const GOOGLE_MARK" in JS
    wait = JS[JS.index("async function walletGoogle("):]
    assert "{do:'google', making: !!making}" in wait
    assert "/api/account/hand?state=" in wait and "setTimeout(r, 2000)" in wait
    assert "10*60*1000" in wait, "asks for as long as the nonce lives"
    for after in ("refreshCoins()", "drawWallet()", "renderAccount()", "renderHome()", "winFocus()"):
        assert after in wait
    css = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")
    assert ".wform .gbtn{" in css and ".wor{" in css
    chrome = (PKG / "static" / "js" / "chrome.js").read_text(encoding="utf-8")
    assert "async function winFocus(" in chrome and "api.focus()" in chrome
    win = (PKG / "window.py").read_text(encoding="utf-8")
    assert "def focus(self)" in win and "SetForegroundWindow" in win


def test_the_hand_route_reads_a_form_before_the_json_body_is_parsed():
    """A form post is not JSON; the route has to take the body itself, ahead
    of the line that parses every other route's JSON."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    post = src[src.index("    def do_POST(self):"):]
    assert post.index('if path == "/api/account/hand":') < post.index("body = self._body()")
    assert "_form_or_json" in post
