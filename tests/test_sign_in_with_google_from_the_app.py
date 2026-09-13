"""Sign in with Google, from the app - through the website, never through an
address on this computer.

lee: *"sign in / sign up and login with google like in the website"*, and
then, looking at a browser tab called 127.0.0.1 that said "That did not
work": *"the app shoud bnever send teh user to a link like thsi with 127.654.
etc it shidu always be teh offical websuet ns eteh sign in with googlw dont
work dont work"*.

Pressing "Continue with Google" makes a secret the app keeps (the verifier)
and opens `mangatct.com/signin?hand=<sha256 of it>`. The page, once the person
is in, files the sign-in with the `handToApp` function under that hash and
says so on the website. The app has been asking `/api/account/hand?state=`
every two seconds; the server asks `takeHand` with the verifier and keeps what
comes back once Google has turned it into a token for the same account.

What is checked here: the address holds only the hash and the verifier is
what collects; a hand is taken once and runs out; a credential Google refuses,
or one for another account, leaves nothing on disk and does not sign out
whoever was in; the app no longer takes a sign-in from a browser at all; the
site page files the hand and never names this computer; and the in-app form
has the button and a real way to reach the page.
"""
import hashlib
import json
import re
import threading
import time
import types
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
def service(monkeypatch, tmp_path):
    """An installed copy that can talk to a project; an account service that
    holds whatever the page filed; and a Google that says yes to two refresh
    tokens (for two different accounts) and no to every other."""
    monkeypatch.delenv(coins.TEST_PURSE, raising=False)
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path))
    monkeypatch.setattr(account, "_repo_config",
                        lambda: {"apiKey": "k", "projectId": "proj", "region": "us-central1"})
    monkeypatch.setattr(account, "HAND_ASK_EVERY", 0.0)
    account._MEM.clear()
    account._HANDS.clear()
    filed, asks = {}, []

    def post(url, body, token=""):
        if url.startswith(account.REFRESH):
            rt = body.get("refresh_token")
            if rt in ("good-refresh", "other-refresh"):
                return {"id_token": "id.tok", "refresh_token": rt,
                        "user_id": "u1" if rt == "good-refresh" else "u2",
                        "expires_in": "3600"}
            raise account._says({"error": {"message": "INVALID_REFRESH_TOKEN"}}, 400)
        if url.endswith("/takeHand"):
            assert token == "", "takeHand is asked without a sign-in"
            verifier = body["data"]["verifier"]
            asks.append(verifier)
            return {"result": filed.pop(hashlib.sha256(verifier.encode()).hexdigest(), None)
                    or {"waiting": True}}
        if url.endswith("/me"):
            return {"result": {"username": "lee", "coins": 12, "verified": True}}
        raise AssertionError("unexpected call " + url)
    monkeypatch.setattr(account, "_post", post)
    return types.SimpleNamespace(filed=filed, asks=asks)


def _file(service, url, **hand):
    """What the page does once the person is in: files a sign-in under the
    hash in its own address."""
    challenge = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["hand"][0]
    service.filed[challenge] = hand


def _serve(p):
    was, editor.PROJECT = editor.PROJECT, p
    srv = editor.ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, was, "http://127.0.0.1:%d" % srv.server_address[1]


def _stop(srv, was):
    srv.shutdown()
    srv.server_close()
    editor.PROJECT = was


def _json(base, route, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + route, data, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw.decode("utf8", "replace")}


# ------------------------------------------------------------------ the hand

def test_the_address_holds_only_the_hash_and_the_secret_collects(service):
    got = account.begin_handoff()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(got["url"]).query)
    assert got["url"].startswith("https://mangatct.com/signin?")
    assert set(q) == {"hand"} and re.fullmatch(r"[0-9a-f]{64}", q["hand"][0])
    verifier = account._HANDS[got["state"]]["verifier"]
    assert q["hand"][0] == hashlib.sha256(verifier.encode()).hexdigest()
    assert verifier not in got["url"] and got["state"] not in got["url"]
    assert "127.0.0.1" not in got["url"] and "app=" not in got["url"]

    # nothing filed yet: waiting, and the service was asked with the secret
    assert account.handoff_state(got["state"]) == {"known": True, "done": False, "who": ""}
    assert service.asks == [verifier]

    _file(service, got["url"], refreshToken="good-refresh", uid="u1", email="lee@x.y")
    assert account.handoff_state(got["state"]) == {"known": True, "done": True, "who": "lee"}
    assert account.signed_in()
    d = account._read()
    assert d["refreshToken"] == "good-refresh" and d["uid"] == "u1" and d["username"] == "lee"
    # done is done: nothing more is asked
    n = len(service.asks)
    assert account.handoff_state(got["state"])["done"] is True and len(service.asks) == n
    assert account.handoff_state("nope") == {"known": False, "done": False}


def test_making_an_account_opens_the_page_on_its_sign_up_side(service):
    got = account.begin_handoff(making=True)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(got["url"]).query)
    assert q["new"] == ["1"] and set(q) == {"hand", "new"}


def test_the_service_is_not_asked_more_often_than_the_floor(service, monkeypatch):
    monkeypatch.setattr(account, "HAND_ASK_EVERY", 60.0)
    got = account.begin_handoff()
    account.handoff_state(got["state"])
    account.handoff_state(got["state"])
    account.handoff_state(got["state"])
    assert len(service.asks) == 1, "two windows polling one hand are one call"


def test_a_hand_that_ran_out_is_forgotten(service):
    got = account.begin_handoff()
    _file(service, got["url"], expired=True)
    st = account.handoff_state(got["state"])
    assert st["known"] is False and "ran out" in st["problem"]
    assert not account.signed_in()
    # and ten minutes on this side is gone too, without asking anybody
    got = account.begin_handoff()
    account._HANDS[got["state"]]["at"] -= account.HAND_FOR + 1
    n = len(service.asks)
    assert account.handoff_state(got["state"]) == {"known": False, "done": False}
    assert len(service.asks) == n
    with pytest.raises(account.AccountError) as e:
        account.finish_handoff(got["state"], "good-refresh")
    assert e.value.code == "stale"


def test_a_credential_google_refuses_leaves_nothing_behind(service):
    got = account.begin_handoff()
    _file(service, got["url"], refreshToken="made-up", uid="u1")
    st = account.handoff_state(got["state"])
    assert st["known"] is False and st["problem"]
    assert not account.signed_in()
    assert account._read().get("refreshToken", "") == ""


def test_a_sign_in_for_another_account_is_refused(service):
    """The service saw u1 sign in; a token that turns out to be u2's is not
    kept, whoever filed it."""
    got = account.begin_handoff()
    _file(service, got["url"], refreshToken="other-refresh", uid="u1")
    st = account.handoff_state(got["state"])
    assert st["known"] is False and "different account" in st["problem"]
    assert not account.signed_in()


def test_a_bad_hand_does_not_sign_out_whoever_was_in(service):
    account._keep({"refreshToken": "good-refresh", "idToken": "old", "localId": "u1",
                   "email": "lee@x.y"})
    got = account.begin_handoff()
    _file(service, got["url"], refreshToken="made-up", uid="u1")
    account.handoff_state(got["state"])
    assert account._read()["refreshToken"] == "good-refresh"


def test_an_unconfigured_copy_says_so_instead_of_opening_anything(monkeypatch, tmp_path):
    monkeypatch.setattr(account, "_repo_config", lambda: {})
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path))
    account._MEM.clear()
    with pytest.raises(account.AccountError) as e:
        account.begin_handoff()
    assert e.value.code == "unconfigured"


# ------------------------------------------------------------ through the app

def test_the_button_opens_the_website_and_the_poll_signs_the_app_in(
        service, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(editor.webbrowser, "open", lambda u: opened.append(u))
    p = Project(None, str(tmp_path / "out"))
    srv, was, base = _serve(p)
    try:
        code, got = _json(base, "/api/account", {"do": "google"})
        assert code == 200 and got["ok"] and got["state"] and got["url"]
        for _ in range(50):
            if opened:
                break
            time.sleep(0.05)
        assert opened == [got["url"]], "the system browser, on the website"
        assert opened[0].startswith("https://mangatct.com/signin?hand=")
        assert str(srv.server_address[1]) not in opened[0], "the page is not told where the app is"

        code, st = _json(base, "/api/account/hand?state=" + got["state"])
        assert code == 200 and st == {"known": True, "done": False, "who": ""}

        _file(service, got["url"], refreshToken="good-refresh", uid="u1", email="lee@x.y")
        code, st = _json(base, "/api/account/hand?state=" + got["state"])
        assert st["done"] is True and st["who"] == "lee"
        assert st["signed_in"] is True and st["balance"] == 12, "the purse, painted at once"
    finally:
        _stop(srv, was)


def test_the_app_no_longer_takes_a_sign_in_from_a_browser(service, tmp_path):
    """The route a browser used to post a credential to is gone: nothing can
    sign this app in by sending a page to it."""
    p = Project(None, str(tmp_path / "out"))
    srv, was, base = _serve(p)
    try:
        code, got = _json(base, "/api/account", {"do": "google", "open": False})
        code, _ = _json(base, "/api/account/hand",
                        {"state": got["state"], "refreshToken": "good-refresh"})
        assert code != 200 and not account.signed_in()
    finally:
        _stop(srv, was)
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    post = src[src.index("    def do_POST(self):"):]
    assert 'if path == "/api/account/hand":' not in post
    assert "_handed_page" not in src and "_form_or_json" not in src
    assert not hasattr(account, "hand_origins") and not hasattr(account, "HAND_ORIGINS")


# ------------------------------------------------------------------- the site

def test_the_site_page_files_the_hand_and_never_names_this_computer():
    assert "127.0.0.1" not in SIGNIN and "f.submit()" not in SIGNIN
    assert "/api/account/hand" not in SIGNIN
    assert "q.get('hand')" in SIGNIN and "/^[0-9a-f]{64}$/.test(hand)" in SIGNIN
    assert ("call('handToApp')({ challenge: forApp.hand, refreshToken: user.refreshToken || '' })"
            in SIGNIN)
    assert 'id="handed"' in SIGNIN and "You are signed in" in SIGNIN
    assert "$('handed').hidden = false;" in SIGNIN and "$('signCard').hidden = true;" in SIGNIN
    # every way in ends the same way: `arrive`, which hands or goes on
    assert "askName(() => arrive(made.user))" in SIGNIN
    assert "arrive(got.user)" in SIGNIN and "arrive(cred.user)" in SIGNIN
    assert "if (forApp && forApp.hand && user) handToApp(user);\n  else location.href = next;" in SIGNIN
    # already signed in: asked, not assumed
    assert "$('useMe').onclick = () => arrive(u);" in SIGNIN and "signOut(auth)" in SIGNIN
    # an older app that still opens `?app=` is told to update, and nothing is sent
    assert "if (q.get('app')) return { old: true };" in SIGNIN and "updates itself" in SIGNIN
    css = (PKG / "site" / "style.css").read_text(encoding="utf-8")
    assert ".forapp{" in css and ".forapp.done{" in css


def test_the_two_functions_meet_in_the_middle():
    fn = (PKG / "firebase" / "functions" / "index.js").read_text(encoding="utf-8")
    assert "export const handToApp = onCall(" in fn and "export const takeHand = onCall(" in fn
    hand = fn[fn.index("export const handToApp"):fn.index("export const takeHand")]
    assert "must(req.auth)" in hand and "/^[0-9a-f]{64}$/" in hand and ".create({" in hand
    take = fn[fn.index("export const takeHand"):]
    take = take[:take.index("\n});\n")]
    assert "createHash('sha256').update(verifier).digest('hex')" in take
    assert "tx.delete(handRef(challenge))" in take and "HAND_FOR_MS" in take
    assert "must(" not in take, "nobody is signed in yet - that is the point"
    rules = (PKG / "firebase" / "firestore.rules").read_text(encoding="utf-8")
    assert "match /{document=**} {\n      allow read, write: if false;" in rules, \
        "hands/* is closed to every client"
    # the app and the function hash the secret the same way
    assert account.hand_challenge("abc") == hashlib.sha256(b"abc").hexdigest()


# -------------------------------------------------------------------- the app

def test_the_app_form_has_the_google_button_and_a_real_way_to_the_page():
    body = JS[JS.index("function walletSignIn("):]
    assert 'class="gbtn" onclick="walletGoogle(' in body
    assert "Continue with Google" in body and "Sign up with Google" in body
    assert "or with an email" in body
    assert "function walletGoogle(" in JS and "const GOOGLE_MARK" in JS
    wait = JS[JS.index("async function walletGoogle("):JS.index("function walletOpenHand(")]
    assert "{do:'google', making: !!making, open: !inApp}" in wait
    assert "if(inApp && _handUrl) walletOpenUrl(_handUrl);" in wait, "the window opens it, in front"
    assert "/api/account/hand?state=" in wait and "setTimeout(r, 2000)" in wait
    assert "10*60*1000" in wait, "asks for as long as the hand lives"
    for after in ("refreshCoins()", "drawWallet()", "renderAccount()", "renderHome()", "winFocus()"):
        assert after in wait
    # lee: *"make teh go here link more visible"* - a button, and a way out
    assert "Open the sign-in page" in wait and "walletOpenHand()" in wait
    assert "walletCancelHand()" in wait
    assert "async function walletOpenUrl(" in JS and "api.open_url(url)" in JS
    assert "if(_handUrl) walletOpenUrl(_handUrl);" in JS
    assert "go there" not in JS and "127.0.0.1" not in JS
    css = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")
    assert ".wnote.whand{" in css and ".whandrow{" in css
    assert ".wform .gbtn{" in css and ".wor{" in css
    chrome = (PKG / "static" / "js" / "chrome.js").read_text(encoding="utf-8")
    assert "async function winFocus(" in chrome and "api.focus()" in chrome
    win = (PKG / "window.py").read_text(encoding="utf-8")
    assert "def focus(self)" in win and "SetForegroundWindow" in win


def test_a_sign_in_google_says_is_dead_signs_the_app_out(service):
    """The account deleted on the website, disabled, or signed out everywhere:
    the next turn of the token signs this machine out, instead of leaving a
    screen that says signed in and can do nothing."""
    account._keep({"refreshToken": "made-up", "idToken": "", "localId": "u1",
                   "email": "lee@x.y", "expiresIn": 0})
    assert account.signed_in()
    with pytest.raises(account.NotSignedIn):
        account.token(force=True)
    assert not account.signed_in()
    assert "INVALID_REFRESH_TOKEN" in account.SIGN_IN_GONE and "USER_NOT_FOUND" in account.SIGN_IN_GONE


def test_the_site_offers_this_account_only_to_somebody_signed_in():
    """lee: *"that sjoud ony be an option while im accly signed in teh ine
    websiet because hwo does it knwo which account to sign in to"*."""
    css = (PKG / "site" / "style.css").read_text(encoding="utf-8")
    assert "[hidden]{display:none !important}" in css, "a class with display must not un-hide"
    assert '<div class="forapp-row" id="forAppRow" hidden>' in SIGNIN
    assert 'id="handed" hidden' in SIGNIN
    who = SIGNIN[SIGNIN.index("whoAmI().then((u) => {"):]
    assert who.index("if (!u) return;") < who.index("$('forAppRow').hidden = false;")
