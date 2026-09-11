"""The account the coins live in.

lee: *"make an account systme with isgn in and sign up and allow the user to
secelt their usernam that need to be unique, do in with firebase ... and make
te coisn be srored on teh firebase database"*.

This is the editor's half of that. The other half is `firebase/` - the rules,
the Cloud Functions and the Stripe webhook - and the split between them is the
whole design:

**The editor never writes a balance.** It runs on the customer's machine, so
everything it can reach they can reach; with their own ID token and a terminal
they can send any request the security rules permit. So the rules permit none
that touch money. Every coin that moves, moves inside a Cloud Function, and
this file only asks.

What it keeps on disk is a refresh token, which is a credential and is written
with the file mode to match. What it keeps in memory is an ID token, which
lasts an hour and is fetched again when it does not.

## Where the keys come from

Nothing in here is a secret. A Firebase web API key is an identifier, not a
password - it says which project, and the rules say what may be done. So it can
sit in a file in the repository, and it does: `site/config.js`, the one file
that gets filled in, read by the website and by this.

    MANGATL_FIREBASE_KEY / _PROJECT / _REGION   environment, wins
    ~/.mangatl/firebase.json                    per machine
    site/config.js                              the repository's own

With none of them set, `configured()` is False and the editor keeps its local
purse - which is what a fresh clone with no Firebase project should do.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import userdata

FILE = "account.json"
CONF = "firebase.json"

IDENTITY = "https://identitytoolkit.googleapis.com/v1/accounts:"
REFRESH = "https://securetoken.googleapis.com/v1/token"

# How long a fetched balance is trusted. The top bar reads it on every page
# turn; a request per page turn is a request per page turn, and the number only
# changes when this process spends or when a payment lands on the website.
FRESH_FOR = 20.0

# An ID token is good for an hour. Asked for again a minute early, because a
# token that expires in flight fails a call that was about to spend money.
EARLY = 60.0

TIMEOUT = 20.0

_LOCK = threading.RLock()
_MEM: dict = {}


class AccountError(Exception):
    """Something the person should be told, in words they can act on."""

    def __init__(self, says: str, code: str = ""):
        super().__init__(says)
        self.code = code


class NotEnough(AccountError):
    """The purse is short. Carries by how much, so the screen can say."""

    def __init__(self, says: str, short: int = 0, balance: int = 0):
        super().__init__(says, "not-enough")
        self.short = int(short or 0)
        self.balance = int(balance or 0)


class NotSignedIn(AccountError):
    def __init__(self, says: str = "Sign in first."):
        super().__init__(says, "unauthenticated")


# ------------------------------------------------------------------- config

def _repo_config() -> dict:
    """The values out of `site/config.js`.

    Read with a regular expression rather than by running it, because it is
    JavaScript and this is Python, and because a config file that can execute
    is a config file that can do anything. Only the four names are taken; the
    comments around them are ignored.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "site", "config.js")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(here), "site", "config.js")
    try:
        with open(path, encoding="utf8") as fh:
            src = fh.read()
    except OSError:
        return {}

    def find(name, where=src):
        m = re.search(r'\b%s\s*:\s*[\'"]([^\'"]*)[\'"]' % name, where)
        return m.group(1) if m else ""

    block = re.search(r"FIREBASE\s*=\s*\{(.*?)\n\}", src, re.S)
    inner = block.group(1) if block else ""
    out = {"apiKey": find("apiKey", inner), "projectId": find("projectId", inner)}
    m = re.search(r'REGION\s*=\s*[\'"]([^\'"]+)[\'"]', src)
    out["region"] = m.group(1) if m else ""
    return {k: v for k, v in out.items() if v}


def _machine_config() -> dict:
    try:
        with open(os.path.join(userdata.user_dir(), CONF), encoding="utf8") as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


_CONF = {"at": 0.0, "got": None}
CONF_FOR = 5.0


def config() -> dict:
    """Which Firebase project, and where its functions live.

    Held for a few seconds. It is asked through `signed_in` -> `configured`
    on nearly every purse read - a chapter's quote asks a few hundred times
    - and each answer used to be two files opened and a regular expression
    run over one of them. Cheap on Linux, not cheap on a Windows disk with
    an antivirus watching it. lee: *"the coins take a long time to show
    up"*. The environment variables are read every time; only the files
    are held."""
    now = time.time()
    # Keyed on which readers and which home answered, so a test that swaps
    # either (monkeypatch) or points the home elsewhere is not handed the
    # previous answer.
    key = (id(_repo_config), id(_machine_config), userdata.user_dir())
    if _CONF["got"] is not None and _CONF.get("key") == key and now - _CONF["at"] < CONF_FOR:
        got = dict(_CONF["got"])
    else:
        got = dict(_repo_config())
        got.update({k: v for k, v in _machine_config().items() if v})
        _CONF.update(at=now, got=dict(got), key=key)
    for key, env in (("apiKey", "MANGATL_FIREBASE_KEY"),
                     ("projectId", "MANGATL_FIREBASE_PROJECT"),
                     ("region", "MANGATL_FIREBASE_REGION")):
        if os.environ.get(env):
            got[key] = os.environ[env]
    got.setdefault("region", "us-central1")
    # A placeholder is not configuration. The file ships with one so the shape
    # is obvious, and a placeholder that counted as set would mean every call
    # failing with Google's error instead of ours.
    if "YOUR" in (got.get("apiKey") or "").upper():
        got["apiKey"] = ""
    return got


def configured() -> bool:
    """True when there is a project to talk to."""
    c = config()
    return bool(c.get("apiKey") and c.get("projectId"))


# -------------------------------------------------------------- the tokens

def _path() -> str:
    return os.path.join(userdata.user_dir(), FILE)


def _read() -> dict:
    with _LOCK:
        if _MEM.get("_at") and _MEM["_at"] > time.time() - 2:
            return dict(_MEM)
        try:
            with open(_path(), encoding="utf8") as fh:
                got = json.load(fh)
        except (OSError, ValueError):
            got = {}
        if not isinstance(got, dict):
            got = {}
        _MEM.clear()
        _MEM.update(got)
        _MEM["_at"] = time.time()
        return dict(got)


def _write(d: dict) -> None:
    with _LOCK:
        _MEM.clear()
        _MEM.update(d)
        _MEM["_at"] = time.time()
        folder = userdata.user_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            tmp = _path() + ".tmp"
            # Written 0600 BEFORE anything goes in it. A refresh token is a
            # credential: it is the thing that gets a new ID token for ever,
            # and it must not be readable by another account on the machine.
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf8") as fh:
                json.dump({k: v for k, v in d.items() if not k.startswith("_")},
                          fh, indent=1)
            os.replace(tmp, _path())
        except OSError:
            pass


def sign_out() -> None:
    """Forget the tokens. Nothing is revoked - signing out of this machine is
    not signing out of the account."""
    with _LOCK:
        _write({})
        try:
            os.remove(_path())
        except OSError:
            pass
        _MEM.clear()


def signed_in() -> bool:
    return bool(configured() and _read().get("refreshToken"))


def who() -> dict:
    """Who this machine is signed in as, from the file. No network."""
    d = _read()
    return {"uid": d.get("uid", ""), "email": d.get("email", ""),
            "username": d.get("username", ""), "photo": d.get("photo", "")}


# ------------------------------------------------------------------ the wire

def _post(url: str, body: dict, token: str = "") -> dict:
    data = json.dumps(body).encode("utf8")
    head = {"Content-Type": "application/json"}
    if token:
        head["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=head, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            got = json.loads(e.read().decode("utf8") or "{}")
        except ValueError:
            got = {}
        raise _says(got, e.code) from None
    except urllib.error.URLError as e:
        raise AccountError("No connection to the account server.",
                           "offline") from e
    except (TimeoutError, OSError) as e:
        raise AccountError("The account server did not answer.",
                           "offline") from e


# Firebase's error strings, as sentences. A form that says
# "INVALID_LOGIN_CREDENTIALS" has told the person nothing they can act on.
SAYS = {
    "EMAIL_EXISTS": "There is already an account with that email.",
    "INVALID_LOGIN_CREDENTIALS": "That email and password do not match an account.",
    "INVALID_PASSWORD": "That email and password do not match an account.",
    "EMAIL_NOT_FOUND": "There is no account with that email.",
    "INVALID_EMAIL": "That does not look like an email address.",
    "MISSING_PASSWORD": "Enter a password.",
    "WEAK_PASSWORD": "Six characters at least.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many tries. Wait a minute and go again.",
    "USER_DISABLED": "That account has been disabled.",
    "TOKEN_EXPIRED": "Signed out. Sign in again.",
    "INVALID_REFRESH_TOKEN": "Signed out. Sign in again.",
}


def _says(got: dict, http: int = 0) -> AccountError:
    err = got.get("error") or {}
    if isinstance(err, str):
        err = {"message": err}
    raw = str(err.get("message") or "").split(" :")[0].strip()
    status = str(err.get("status") or "")

    if status == "FAILED_PRECONDITION" or raw == "not enough coins":
        d = err.get("details") or {}
        return NotEnough("Not enough coins.", d.get("short"), d.get("balance"))
    if status == "UNAUTHENTICATED" or http == 401:
        return NotSignedIn()
    if raw in SAYS:
        return AccountError(SAYS[raw], raw)
    if status == "ALREADY_EXISTS":
        return AccountError("That name is taken.", "already-exists")
    if raw:
        return AccountError(raw, status or str(http))
    return AccountError("The account server said no.", status or str(http))


def _identity(what: str, body: dict) -> dict:
    c = config()
    if not c.get("apiKey"):
        raise AccountError("No Firebase project is configured.", "unconfigured")
    return _post("%s%s?key=%s" % (IDENTITY, what,
                                 urllib.parse.quote(c["apiKey"])), body)


def _keep(got: dict, **extra) -> None:
    d = _read()
    d.update({
        "idToken": got.get("idToken") or got.get("id_token") or "",
        # A reply with no refresh token in it is not a sign-out. Google's
        # refresh endpoint always returns one; anything else that lands here
        # keeps the credential that got it.
        "refreshToken": got.get("refreshToken") or got.get("refresh_token")
                        or d.get("refreshToken", ""),
        "uid": got.get("localId") or got.get("user_id") or d.get("uid", ""),
        "email": got.get("email") or d.get("email", ""),
        "expires": time.time() + float(got.get("expiresIn")
                                       or got.get("expires_in") or 3600),
    })
    d.update(extra)
    _write(d)


def token(force: bool = False) -> str:
    """A live ID token, refreshed if the one on disk has run out.

    `force`: fetch a new one even though the old one has time left. The
    token carries `email_verified`, and it is minted when it is minted: for
    up to an hour after the person clicks the link in the mail, the token
    the editor holds still says the address is unverified, and the server -
    which reads the token and nothing else - keeps the hundred coins back.
    A refresh is what turns the claim over."""
    d = _read()
    if not d.get("refreshToken"):
        raise NotSignedIn()
    if not force and d.get("idToken") and float(d.get("expires") or 0) > time.time() + EARLY:
        return d["idToken"]
    c = config()
    got = _post("%s?key=%s" % (REFRESH, urllib.parse.quote(c.get("apiKey", ""))),
                {"grant_type": "refresh_token",
                 "refresh_token": d["refreshToken"]})
    _keep(got)
    return _read().get("idToken") or ""


def function_url(name: str) -> str:
    """Where one of the Cloud Functions answers. The relay (`editor.
    relay_url`) is reached the same way as the callables."""
    c = config()
    if not c.get("projectId"):
        raise AccountError("No Firebase project is configured.", "unconfigured")
    return "https://%s-%s.cloudfunctions.net/%s" % (
        c.get("region") or "us-central1", c["projectId"], name)


def call(name: str, data: dict | None = None) -> dict:
    """One of the Cloud Functions, as a callable.

    The wire format is Google's: `{"data": ...}` in, `{"result": ...}` out.
    Spoken by hand rather than through a client library, because the library
    for this is the JavaScript one and the editor is Python.
    """
    url = function_url(name)
    got = _post(url, {"data": data or {}}, token())
    if "error" in got:
        raise _says(got)
    out = got.get("result")
    return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------- signing in

def sign_in(email: str, password: str) -> dict:
    got = _identity("signInWithPassword", {
        "email": (email or "").strip(), "password": password or "",
        "returnSecureToken": True})
    _keep(got)
    _MEM.pop("balance", None)
    return refresh_me()


def sign_up(email: str, password: str, username: str = "") -> dict:
    """A new account, and its name in the same breath.

    The name is claimed AFTER the account exists, because claiming it needs an
    ID token and there is no token until there is an account. If the name turns
    out to be taken, the account is still made and still signed in - losing a
    working account over a name somebody else already had would be the wrong
    way round, and the name can be set on the account page.
    """
    got = _identity("signUp", {
        "email": (email or "").strip(), "password": password or "",
        "returnSecureToken": True})
    _keep(got)
    _MEM.pop("balance", None)
    if username:
        try:
            claim_username(username)
        except AccountError:
            pass
    # The link that makes the address a verified one - and a verified one is
    # what the hundred free coins are given to. Best effort: an account that
    # was made is an account, and the coin panel offers the mail again.
    try:
        send_verification()
    except AccountError:
        pass
    return refresh_me()


# ------------------------------------------------- signing in, in the browser

# lee: *"sign in / sign up and login with google like in the website"*.
#
# Google's sign-in is a popup on a Google page, and it wants a real browser:
# the app's window is a WebView with no address bar, and a Google password
# typed into a box the app drew is the one thing the website's flow exists
# to avoid. So the app does not draw it. It opens the website's own sign-in
# page in the system browser, marked as being FOR THE APP -
# `signin?app=<port>&state=<nonce>` - and the page, once the person is in
# (with Google or with an email), hands the credential to the app: a form
# post to 127.0.0.1:<port>, which a browser allows because a top-level post
# to the loopback is not a cross-site fetch it polices. The nonce is what
# makes a hand acceptable: minted here, sent out once, good for ten minutes,
# spent on use. A post with no nonce, an old one, or one from a page that is
# not ours, is refused.
#
# What is handed over is the same thing an email sign-in keeps: a refresh
# token. Nothing about how the person signed in is different afterwards.

SITE = "https://mangatct.com"
#: Pages allowed to hand a sign-in to the app: the site by its own name, and
#: by the Firebase names the same pages are served under.
HAND_ORIGINS = (SITE, "https://www.mangatct.com")
#: A hand is good for this long after the browser opened.
HAND_FOR = 600.0

_HANDS: dict = {}       # nonce -> {"at": when minted, "done": bool, "who": ""}


def hand_origins() -> tuple:
    c = config()
    extra: tuple = ()
    if c.get("projectId"):
        extra = ("https://%s.web.app" % c["projectId"],
                 "https://%s.firebaseapp.com" % c["projectId"])
    return HAND_ORIGINS + extra


def _tidy_hands(now: float | None = None) -> None:
    now = time.time() if now is None else now
    for k in [k for k, v in _HANDS.items() if now - v["at"] > HAND_FOR]:
        _HANDS.pop(k, None)


def begin_handoff(port: int, making: bool = False) -> dict:
    """Mint a nonce and say where the browser should go. `making`: open the
    page on its Create-an-account side (the site's `?new=1`)."""
    if not configured():
        raise AccountError("No Firebase project is configured.", "unconfigured")
    import secrets
    with _LOCK:
        _tidy_hands()
        nonce = secrets.token_urlsafe(24)
        _HANDS[nonce] = {"at": time.time(), "done": False, "who": ""}
    q = {"app": str(int(port)), "state": nonce}
    if making:
        q["new"] = "1"
    return {"state": nonce, "url": SITE + "/signin?" + urllib.parse.urlencode(q)}


def handoff_state(nonce: str) -> dict:
    """What the app polls: is this hand done, and who came in."""
    with _LOCK:
        _tidy_hands()
        h = _HANDS.get(str(nonce or ""))
        if not h:
            return {"known": False, "done": False}
        return {"known": True, "done": bool(h["done"]), "who": h["who"]}


def finish_handoff(nonce: str, refresh_token: str, id_token: str = "",
                   uid: str = "", email: str = "", origin: str = "") -> dict:
    """The browser hands a credential over. Checked before it is kept: the
    nonce is one we minted and still live, the page is ours, and the refresh
    token gets a real ID token from Google - a made-up one is refused there,
    and nothing of it is left on disk."""
    nonce = str(nonce or "")
    if origin and origin.rstrip("/") not in hand_origins():
        raise AccountError("That page may not sign the app in.", "origin")
    with _LOCK:
        _tidy_hands()
        h = _HANDS.get(nonce)
        if not h:
            raise AccountError("This sign-in link has expired. Press the "
                               "button in the app again.", "stale")
        if h["done"]:
            raise AccountError("This sign-in was already used.", "used")
        if not refresh_token:
            raise AccountError("No credential came with it.", "empty")
        before = _read()
        _keep({"refreshToken": str(refresh_token), "idToken": str(id_token or ""),
               "localId": str(uid or ""), "email": str(email or ""),
               "expiresIn": 0})
        try:
            token(force=True)            # proves the credential; keeps the token
            _MEM.pop("balance", None)
            got = refresh_me()
        except AccountError:
            # Not a credential of ours after all. Put back what was there.
            if before.get("refreshToken"):
                _write({k: v for k, v in before.items() if not k.startswith("_")})
            else:
                sign_out()
            raise
        h["done"] = True
        h["who"] = _read().get("email") or email
    return got


def reset_password(email: str) -> None:
    _identity("sendOobCode", {"requestType": "PASSWORD_RESET",
                              "email": (email or "").strip()})


def send_verification() -> None:
    """The verification mail, to the signed-in account's own address. The
    link in it lands on the website's account page, which is where the
    coins are first seen; the editor sees them on its next look."""
    _identity("sendOobCode", {"requestType": "VERIFY_EMAIL",
                              "idToken": token()})


# How often, while the free coins are still owed, the editor turns its token
# over on its own to see whether the link has been clicked. The person can
# press the button and not wait; this is for the one who clicked the link and
# came back to the editor expecting the number to have changed.
RECHECK_VERIFIED = 300.0


def _turn_token() -> None:
    """A fresh ID token now, and a note of when, so the automatic turnover in
    `refresh_me` does not do it again a moment later."""
    try:
        token(force=True)
    except AccountError:
        pass
    d = _read()
    d["token_turned"] = time.time()
    _write(d)


def claim_welcome() -> dict:
    """The person says they clicked the link: fetch a token that knows, and
    ask the server - which gives the coins on that same call if it is so."""
    _turn_token()
    _MEM.pop("balance", None)
    return refresh_me()


def claim_username(name: str) -> str:
    got = call("claimUsername", {"username": name})
    d = _read()
    d["username"] = got.get("username") or name
    _write(d)
    return d["username"]


def refresh_me() -> dict:
    """Ask the server what the account holds, and remember it."""
    d = _read()
    if d.get("welcome_due") and not d.get("verified") \
            and time.time() - float(d.get("token_turned") or 0) > RECHECK_VERIFIED:
        # The coins are owed and the token on disk was minted unverified.
        # Turn it over now and then, so a link clicked in a browser reaches
        # the editor within minutes rather than within the hour.
        _turn_token()
    got = call("me")
    d = _read()
    d["username"] = got.get("username") or d.get("username", "")
    d["photo"] = got.get("photo") or d.get("photo", "")
    d["plan"] = got.get("plan") or {}
    d["balance"] = int(got.get("coins") or 0)
    d["verified"] = bool(got.get("verified"))
    w = got.get("welcome") or {}
    d["welcome_due"] = bool(w.get("due"))
    d["welcome_coins"] = int(w.get("coins") or 0)
    d["welcome_given"] = bool(w.get("given"))
    d["checked"] = time.time()
    _write(d)
    return got


def balance(fresh: bool = False) -> int:
    """Coins on the account. Cached for a few seconds, because the top bar
    asks on every page turn."""
    d = _read()
    if not d.get("refreshToken"):
        raise NotSignedIn()
    if fresh:
        # Asked for the truth, so a connection that cannot supply it is an
        # error and not a shrug. This is the path taken just before money
        # moves; the last number known is not good enough to decide on.
        refresh_me()
    elif time.time() - float(d.get("checked") or 0) > FRESH_FOR:
        if d.get("checked"):
            # A number is known, only stale: answer with it now and ask the
            # server behind the screen. The run dialog's prices used to wait
            # on this call - a cold Cloud Function is seconds - and the
            # coins on its buttons came up long after the buttons did.
            # lee: *"the coins took a long time to show up"*.
            _refresh_behind()
        else:
            try:
                refresh_me()
            except AccountError:
                # Drawing a balance, not deciding on one. Nothing is known
                # yet, so this once the screen waits for the answer.
                pass
    return int(_read().get("balance") or 0)


_BEHIND = {"on": False}
_BEHIND_LOCK = threading.Lock()


def _refresh_behind() -> None:
    """One `refresh_me` in a thread; a second ask while it runs joins it."""
    with _BEHIND_LOCK:
        if _BEHIND["on"]:
            return
        _BEHIND["on"] = True

    def go():
        try:
            refresh_me()
        except Exception:
            pass
        finally:
            with _BEHIND_LOCK:
                _BEHIND["on"] = False
    threading.Thread(target=go, daemon=True).start()


def new_run() -> str:
    """An id for one run of one step.

    It is what makes a charge happen once. A request that times out may well
    have been received; the client that retries it sends the same id, and the
    function recognises it and does not charge twice.
    """
    import uuid
    return uuid.uuid4().hex


def spend(coins: int, what: str = "ai", page: str = "", run: str = "") -> int:
    """Take coins off the account. Raises `NotEnough` rather than going under."""
    coins = int(coins or 0)
    if coins <= 0:
        return 0
    got = call("spendCoins", {"coins": coins, "what": what, "page": page,
                              "run": run or new_run()})
    d = _read()
    d["balance"] = int(got.get("balance") or 0)
    d["checked"] = time.time()
    _write(d)
    return int(got.get("coins") or 0)


def ledger(n: int = 50) -> dict:
    """The account's receipt, newest first: `{"rows": [...], "packs": {...}}`.
    Asked of the `ledgerLines` function; the website reads the same lines."""
    return call("ledgerLines", {"n": int(n)})


#: The pictures the website offers, in its order. `iconSvg` there draws each
#: from its index; `static/js/coins.js` draws the same ten the same way.
ICONS = ("fox", "cat", "moon", "star", "bolt", "leaf", "wave", "ink", "panel", "brush")


def set_photo(icon: str) -> dict:
    """Pick the account's picture - one of `ICONS`. Written straight to the
    account document over Firestore's REST face with the person's own token,
    exactly as the website does with the client SDK: the rules let a person
    write `photo` on their own document and nothing else."""
    icon = str(icon or "").strip()
    if icon not in ICONS:
        raise AccountError("Not one of the pictures.", "bad-photo")
    c = config()
    d = _read()
    uid = d.get("uid") or ""
    if not uid:
        raise NotSignedIn()
    url = ("https://firestore.googleapis.com/v1/projects/%s/databases/(default)/"
           "documents/users/%s?updateMask.fieldPaths=photo"
           % (urllib.parse.quote(c["projectId"]), urllib.parse.quote(uid)))
    body = json.dumps({"fields": {"photo": {"stringValue": icon}}}).encode("utf8")
    req = urllib.request.Request(url, data=body, method="PATCH", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + token()})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            r.read()
    except urllib.error.HTTPError as e:
        raise AccountError("The picture could not be saved (%d)." % e.code, "photo") from None
    except (urllib.error.URLError, OSError) as e:
        raise AccountError("No connection to the account server.", "offline") from e
    d = _read()
    d["photo"] = icon
    _write(d)
    return {"photo": icon}


def refund(coins: int, run: str) -> int:
    """Give back part of a run that did not happen. Never more than that run
    took - the function checks, because this one is asked by the client."""
    coins = int(coins or 0)
    if coins <= 0 or not run:
        return 0
    got = call("refundCoins", {"coins": coins, "run": run})
    d = _read()
    d["balance"] = int(got.get("balance") or 0)
    d["checked"] = time.time()
    _write(d)
    return int(got.get("coins") or 0)


def state() -> dict:
    """Everything the top bar needs about the account, in one read.

    The balance goes through `balance()`, so a payment made on the website
    turns up in the editor within `FRESH_FOR` seconds without anybody pressing
    anything - and a page turn in between costs no request at all, because
    that is what the cache is for.
    """
    d = _read()
    live = bool(d.get("refreshToken"))
    coins = balance() if live else 0
    d = _read()
    return {"configured": configured(), "signed_in": live,
            "email": d.get("email", ""), "username": d.get("username", ""),
            "photo": d.get("photo", ""), "plan": d.get("plan") or {},
            "balance": coins,
            # The free coins: owed until the email is verified, and how many.
            # `welcome_due` and not `verified` is the state with a button in
            # it; verified and still due is an address that had its coins on
            # an earlier account, and is shown nothing.
            "verified": bool(d.get("verified")),
            "welcome_due": bool(live and d.get("welcome_due")),
            "welcome_coins": int(d.get("welcome_coins") or 0),
            "welcome_given": bool(d.get("welcome_given"))}


# ------------------------------------------------------------- from the shell

def _main(argv=None) -> int:
    """`python -m mangatl.account` - sign this machine in, and see who it is.

        python -m mangatl.account                    who am I
        python -m mangatl.account signup you@x.com   make an account
        python -m mangatl.account signin you@x.com   sign in
        python -m mangatl.account name lee           take a username
        python -m mangatl.account signout            forget the tokens

    The password is asked for rather than passed as an argument: an argument
    goes in the shell history and in the process list.
    """
    import argparse
    import getpass
    import sys

    ap = argparse.ArgumentParser(prog="python -m mangatl.account",
                                 description="The MangaTCT account (beta).")
    ap.add_argument("what", nargs="?", default="who",
                    choices=("who", "signin", "signup", "signout", "name"))
    ap.add_argument("value", nargs="?", default="")
    a = ap.parse_args(argv)

    if not configured() and a.what != "who":
        print("No Firebase project configured — fill in site/config.js.")
        return 1
    try:
        if a.what == "signout":
            sign_out()
            print("Signed out on this machine.")
            return 0
        if a.what == "name":
            if not a.value:
                ap.error("which name? e.g. `name lee`")
            print("You are %s." % claim_username(a.value))
            return 0
        if a.what in ("signin", "signup"):
            if not a.value:
                ap.error("which email? e.g. `%s you@example.com`" % a.what)
            pw = getpass.getpass("Password: ")
            if a.what == "signup":
                sign_up(a.value, pw, input("Username (optional): ").strip())
            else:
                sign_in(a.value, pw)
        s = state()
        if not s["configured"]:
            print("No Firebase project configured — the local purse is in use.")
            return 0
        if not s["signed_in"]:
            print("Not signed in.")
            return 0
        print("%s%s — %d TCT Coins" % (
            s["username"] or s["email"],
            " (%s)" % s["email"] if s["username"] else "",
            balance(fresh=True)))
        return 0
    except AccountError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
