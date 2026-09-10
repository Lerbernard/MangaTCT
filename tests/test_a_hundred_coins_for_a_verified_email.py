"""A hundred free coins for a new account - once its email is verified.

lee: *"new account shoul get 100 free coins on creation and link the coins on
the website and the coins in the app with the account"*.

The link was already there: signed in, the editor's purse IS the account
(`coins.remote()`), and the website watches the same document. What was not
there was the grant - `ensureUser` opened every account at zero, on purpose,
because a free sample anybody can have again with another address is the
price, not a sample. The grant now has a gate (a verified email, read off the
signed ID token and nothing else) and a memory (once per uid and once per
address), and both halves of the product know how to ask for it.

Nothing here reaches Firebase. The pure part of the decision is run under
node; the talking is held by reading what it says.
"""
import json
import re
import shutil
import subprocess
import time

import pytest

from where import PKG
from mangatl import account, coins

FN = PKG / "firebase" / "functions"
INDEX = (FN / "index.js").read_text(encoding="utf-8")
PURSE = (FN / "purse.js").read_text(encoding="utf-8")


# ------------------------------------------------------------- the decision

def _node(js):
    node = shutil.which("node")
    if not node:
        pytest.skip("no node")
    r = subprocess.run([node, "--input-type=module", "-e", js], cwd=str(FN),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a_hundred_to_a_verified_address_and_nothing_to_anyone_else():
    got = _node("""
      import { welcome, WELCOME } from './purse.js';
      console.log(JSON.stringify({ WELCOME,
        fresh: welcome(0, { verified: true, granted: false }),
        unverified: welcome(0, { verified: false, granted: false }),
        again: welcome(250, { verified: true, granted: true }),
        nothing: welcome(0),
        onTop: welcome('7', { verified: true }) }));""")
    assert got["WELCOME"] == 100
    assert got["fresh"] == {"ok": True, "balance": 100, "coins": 100}
    assert got["unverified"]["ok"] is False and got["unverified"]["coins"] == 0
    assert got["again"]["ok"] is False and got["again"]["balance"] == 250
    assert got["nothing"]["ok"] is False, "no facts, no coins"
    assert got["onTop"]["balance"] == 107, "given on top of what is there"


def test_the_gate_is_the_token_and_the_memory_is_two_places():
    """`email_verified` comes off the signed ID token - not a request field,
    not a Firestore field a client could write. The grant is remembered on
    the uid (`granted.welcome`, the way a Stripe event id is) AND on a hash
    of the address (`welcomed/<sha256>`), so delete-and-recreate with the
    same email gets nothing the second time; the address itself is never
    written down as a document id."""
    body = INDEX[INDEX.index("async function welcomeIfDue"):INDEX.index("/* ---", INDEX.index("async function welcomeIfDue"))]
    assert "tok.email_verified === true" in body
    assert "req.data" not in body, "nothing about verification is taken from the request"
    assert "welcomed/${emailKey(tok.email)}" in body
    assert "createHash('sha256')" in INDEX
    assert "'granted.welcome': true" in body
    assert "tx.create(seen" in body, "a create, so two calls at once cannot both grant"
    assert "kind: 'credit', what: 'welcome'" in body


def test_the_account_still_opens_at_zero_and_me_is_where_the_coins_land():
    """`ensureUser` is unchanged: zero, made by the server. The coins come on
    `me` - the first call every signed-in page and the editor make - once
    the token says verified. There is deliberately no `claimWelcome` call:
    a call a client makes on purpose is a call that can be made for someone
    else's uid the day there is a bug in it."""
    ensure = INDEX[INDEX.index("async function ensureUser"):INDEX.index("async function welcomeIfDue")]
    assert "coins: 0," in ensure
    me = INDEX[INDEX.index("export const me = onCall"):INDEX.index("export const checkout")]
    assert "await welcomeIfDue(uid, req.auth)" in me
    assert "welcome: {" in me and "due:" in me and "given:" in me
    assert "claimWelcome" not in INDEX
    rules = (PKG / "firebase" / "firestore.rules").read_text(encoding="utf-8")
    assert re.search(r"match /welcomed/\{hash\}\s*\{\s*allow read, write: if false;", rules), \
        "the memory of who was welcomed is nobody's to read or write from a client"


# ------------------------------------------------------------------ the site

def test_the_sign_up_sends_the_mail_and_the_account_page_asks_for_the_coins():
    app = (PKG / "site" / "app.js").read_text(encoding="utf-8")
    assert "sendEmailVerification" in app and "export function sendVerifyMail" in app
    assert "account.html?verified=1" in app, "the link lands where the coins are first seen"
    assert "getIdToken(true)" in app, "a token minted before the click still says unverified"
    signin = (PKG / "site" / "signin.html").read_text(encoding="utf-8")
    assert re.search(r"createUserWithEmailAndPassword\(auth, email, pass\);\s*(//[^\n]*\n\s*)*sendVerifyMail\(made\.user\)", signin)
    assert "100 free coins" in signin
    acct = (PKG / "site" / "account.html").read_text(encoding="utf-8")
    assert 'id="welcome"' in acct and "drawWelcome(" in acct
    assert "Send it again" in acct and "I clicked it" in acct
    assert "visibilitychange" in acct, "click the link in the mail tab, come back, it is there"
    assert "if (!w || !w.due || verified) { box.hidden = true; return; }" in acct, \
        "shown only while there is something for the person to do"
    assert "Free coins for signing up" in acct, "not 'Bought welcome' in the ledger"
    pricing = (PKG / "site" / "pricing.html").read_text(encoding="utf-8")
    assert "starts with 100 coins" in pricing


# ---------------------------------------------------------------- the editor

class Wire:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.sent = []

    def __call__(self, url, body, token=""):
        self.sent.append({"url": url, "body": body, "token": token})
        if not self.replies:
            return {}
        got = self.replies.pop(0)
        if isinstance(got, Exception):
            raise got
        return got


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(account, "_repo_config", dict)
    monkeypatch.setenv("MANGATL_FIREBASE_KEY", "AIzaTESTKEY")
    monkeypatch.setenv("MANGATL_FIREBASE_PROJECT", "mangatct")
    monkeypatch.setenv("MANGATL_FIREBASE_REGION", "europe-west1")
    account._MEM.clear()
    yield tmp_path
    account._MEM.clear()


ME_OWED = {"result": {"coins": 0, "username": "lee", "verified": False,
                      "welcome": {"coins": 100, "due": True, "given": False}}}
ME_GIVEN = {"result": {"coins": 100, "username": "lee", "verified": True,
                       "welcome": {"coins": 100, "due": False, "given": True}}}


def test_signing_up_in_the_editor_sends_the_verification_mail(project, monkeypatch):
    wire = Wire(
        {"idToken": "id-1", "refreshToken": "r-1", "localId": "u1",
         "email": "lee@example.com", "expiresIn": "3600"},
        {"result": {"ok": True, "username": "lee"}},
        {"email": "lee@example.com"},                       # sendOobCode
        ME_OWED)
    monkeypatch.setattr(account, "_post", wire)
    account.sign_up("lee@example.com", "hunter2", "lee")
    oob = [c for c in wire.sent if "sendOobCode" in c["url"]]
    assert len(oob) == 1
    assert oob[0]["body"] == {"requestType": "VERIFY_EMAIL", "idToken": "id-1"}
    assert "password" not in json.dumps(oob[0]["body"])
    s = account.state()
    assert s["welcome_due"] is True and s["verified"] is False
    assert s["welcome_coins"] == 100
    # ...and the coin panel, which reads coins.state(), sees the same
    assert coins.state()["welcome_due"] is True


def test_a_mail_that_cannot_be_sent_does_not_cost_the_account(project, monkeypatch):
    wire = Wire(
        {"idToken": "id-1", "refreshToken": "r-1", "localId": "u1",
         "expiresIn": "3600"},
        {"error": {"status": "TOO_MANY_ATTEMPTS_TRY_LATER", "message": "later"}},
        ME_OWED)
    monkeypatch.setattr(account, "_post", wire)
    account.sign_up("lee@example.com", "hunter2")
    assert account.signed_in() is True


def _live(**extra):
    d = {"idToken": "id-old", "refreshToken": "refresh-1", "uid": "u1",
         "email": "lee@example.com", "expires": time.time() + 3000,
         "balance": 0, "checked": time.time()}
    d.update(extra)
    account._write(d)


def test_i_clicked_it_turns_the_token_over_before_asking(project, monkeypatch):
    """The token on disk has fifty minutes left and says unverified. Pressing
    the button must not send THAT one: a refresh first, then `me`, with the
    new token - and the coins come back on that same call."""
    _live(welcome_due=True, verified=False)
    wire = Wire({"id_token": "id-new", "refresh_token": "refresh-1",
                 "user_id": "u1", "expires_in": "3600"}, ME_GIVEN)
    monkeypatch.setattr(account, "_post", wire)
    account.claim_welcome()
    assert wire.sent[0]["url"].startswith(account.REFRESH)
    assert wire.sent[1]["url"].endswith("/me") and wire.sent[1]["token"] == "id-new"
    s = account.state()
    assert s["balance"] == 100 and s["welcome_given"] is True
    assert s["welcome_due"] is False and s["verified"] is True


def test_while_the_coins_are_owed_the_editor_turns_its_token_over_by_itself(project, monkeypatch):
    """Somebody clicks the link in a browser and comes back to the editor
    expecting the number to change. It should not take the hour the old
    token has left - and it should not be a refresh per page turn either."""
    _live(welcome_due=True, verified=False, checked=0)
    wire = Wire({"id_token": "id-new", "refresh_token": "refresh-1",
                 "user_id": "u1", "expires_in": "3600"}, ME_OWED, ME_OWED, ME_OWED)
    monkeypatch.setattr(account, "_post", wire)
    account.balance()                                   # stale -> refresh_me
    assert wire.sent[0]["url"].startswith(account.REFRESH), "turned over once"
    # within the window: page turns ask `me` with the token they have
    d = account._read(); d["checked"] = 0; account._write(d)
    account.balance()
    d = account._read(); d["checked"] = 0; account._write(d)
    account.balance()
    turns = [c for c in wire.sent if c["url"].startswith(account.REFRESH)]
    assert len(turns) == 1, "not one per page turn"
    # once verified, it stops
    d = account._read(); d.update(verified=True, welcome_due=False, checked=0,
                                  token_turned=0); account._write(d)
    account.balance()
    assert len([c for c in wire.sent if c["url"].startswith(account.REFRESH)]) == 1


def test_verified_but_still_owed_shows_no_button(project, monkeypatch):
    """An address that had its coins on an earlier account: verified, and
    `due` stays true because THIS uid was never granted. The panel's rule is
    `welcome_due && !verified`, so nothing is offered that will not come."""
    _live(welcome_due=True, verified=True)
    s = account.state()
    assert s["welcome_due"] is True and s["verified"] is True
    js = (PKG / "static" / "js" / "coins.js").read_text(encoding="utf-8")
    assert "if(!w.welcome_due || w.verified) return '';" in js


def test_the_editor_has_the_two_buttons_and_the_routes_behind_them():
    js = (PKG / "static" / "js" / "coins.js").read_text(encoding="utf-8")
    assert "walletClaim(" in js and "{do: 'claim'}" in js
    assert "walletVerifyMail(" in js and "{do: 'verify'}" in js
    ed = (PKG / "editor.py").read_text(encoding="utf-8")
    assert 'do == "verify"' in ed and "account.send_verification()" in ed
    assert 'do == "claim"' in ed and "account.claim_welcome()" in ed
    css = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")
    assert ".wacct.wwelcome" in css
