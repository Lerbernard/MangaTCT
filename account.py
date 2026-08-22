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


def config() -> dict:
    """Which Firebase project, and where its functions live."""
    got = dict(_repo_config())
    got.update({k: v for k, v in _machine_config().items() if v})
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
        "refreshToken": got.get("refreshToken") or got.get("refresh_token") or "",
        "uid": got.get("localId") or got.get("user_id") or d.get("uid", ""),
        "email": got.get("email") or d.get("email", ""),
        "expires": time.time() + float(got.get("expiresIn")
                                       or got.get("expires_in") or 3600),
    })
    d.update(extra)
    _write(d)


def token() -> str:
    """A live ID token, refreshed if the one on disk has run out."""
    d = _read()
    if not d.get("refreshToken"):
        raise NotSignedIn()
    if d.get("idToken") and float(d.get("expires") or 0) > time.time() + EARLY:
        return d["idToken"]
    c = config()
    got = _post("%s?key=%s" % (REFRESH, urllib.parse.quote(c.get("apiKey", ""))),
                {"grant_type": "refresh_token",
                 "refresh_token": d["refreshToken"]})
    _keep(got)
    return _read().get("idToken") or ""


def call(name: str, data: dict | None = None) -> dict:
    """One of the Cloud Functions, as a callable.

    The wire format is Google's: `{"data": ...}` in, `{"result": ...}` out.
    Spoken by hand rather than through a client library, because the library
    for this is the JavaScript one and the editor is Python.
    """
    c = config()
    if not c.get("projectId"):
        raise AccountError("No Firebase project is configured.", "unconfigured")
    url = "https://%s-%s.cloudfunctions.net/%s" % (
        c.get("region") or "us-central1", c["projectId"], name)
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
    return refresh_me()


def reset_password(email: str) -> None:
    _identity("sendOobCode", {"requestType": "PASSWORD_RESET",
                              "email": (email or "").strip()})


def claim_username(name: str) -> str:
    got = call("claimUsername", {"username": name})
    d = _read()
    d["username"] = got.get("username") or name
    _write(d)
    return d["username"]


def set_photo(icon: str) -> None:
    """The picture icon. Written on the website, mirrored here so the editor
    can draw it without another round trip."""
    d = _read()
    d["photo"] = str(icon or "")[:64]
    _write(d)


# ------------------------------------------------------------------ the purse

def refresh_me() -> dict:
    """Ask the server what the account holds, and remember it."""
    got = call("me")
    d = _read()
    d["username"] = got.get("username") or d.get("username", "")
    d["photo"] = got.get("photo") or d.get("photo", "")
    d["plan"] = got.get("plan") or {}
    d["balance"] = int(got.get("coins") or 0)
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
        try:
            refresh_me()
        except AccountError:
            # Drawing a balance, not deciding on one. The last number known
            # beats showing nothing, and nothing is bought on it.
            pass
    return int(_read().get("balance") or 0)


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
    return {"configured": configured(), "signed_in": live,
            "email": d.get("email", ""), "username": _read().get("username", ""),
            "photo": _read().get("photo", ""), "plan": _read().get("plan") or {},
            "balance": coins}


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
                                 description="The MangaTCT account.")
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
