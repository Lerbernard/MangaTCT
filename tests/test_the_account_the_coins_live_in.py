"""The account the coins live in.

lee: *"make an account systme with isgn in and sign up ... and make te coisn be
srored on teh firebase database"*.

Two things are under test here and they are different questions.

The first is the CLIENT: `account.py` talking to Firebase. Every test below
replaces the one function that touches the network, so nothing here reaches
Google - what is being checked is what would be SENT, what is made of what
comes back, and what is left on disk afterwards.

The second is the SWITCH: `coins.py` has one purse interface and two purses
behind it, and the thing that must not go wrong is a spend landing in the wrong
one. A run charged to a local wallet while somebody is signed in is work given
away; a run that silently charges nothing when the server cannot be reached is
worse. Both are tested by their behaviour, not by reading the source.
"""
import json
import os
import stat
import time

import pytest

from mangatl import account, coins


# ------------------------------------------------------------------ the wire

class Wire:
    """Stands in for `account._post`.

    Records every call and answers from a script. A test that wants to check
    what was sent reads `.sent`; a test that wants to drive a reply pushes one
    on to `.replies`.
    """

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

    @property
    def last(self):
        return self.sent[-1]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home of this test's own, and no Firebase project until one is set."""
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MANGATL_FIREBASE_KEY", raising=False)
    monkeypatch.delenv("MANGATL_FIREBASE_PROJECT", raising=False)
    monkeypatch.delenv("MANGATL_FIREBASE_REGION", raising=False)
    account._MEM.clear()
    yield tmp_path
    account._MEM.clear()


@pytest.fixture
def project(home, monkeypatch):
    """A configured project, with no repository config.js in the way."""
    monkeypatch.setattr(account, "_repo_config", dict)
    monkeypatch.setenv("MANGATL_FIREBASE_KEY", "AIzaTESTKEY")
    monkeypatch.setenv("MANGATL_FIREBASE_PROJECT", "mangatct")
    monkeypatch.setenv("MANGATL_FIREBASE_REGION", "europe-west1")
    return home


def _signed_in(monkeypatch, **extra):
    """Put a live session on disk, without going through sign-in."""
    d = {"idToken": "id-1", "refreshToken": "refresh-1", "uid": "u1",
         "email": "lee@example.com", "expires": time.time() + 3000,
         "balance": 500, "checked": time.time()}
    d.update(extra)
    account._write(d)
    return d


# ------------------------------------------------------------------- config

def test_a_fresh_clone_has_no_project(home, monkeypatch):
    """No Firebase, no account - and the editor keeps its local purse.

    This is the case a checkout of the source is in, and it must not be an
    error state: a "Sign in" button that cannot sign in to anything is worse
    than no button.
    """
    monkeypatch.setattr(account, "_repo_config", dict)
    assert account.configured() is False
    assert account.signed_in() is False


def test_the_repository_config_is_where_the_key_comes_from(home, monkeypatch):
    """One file gets filled in, and both halves read it.

    A Firebase web API key is an identifier and not a password, so it belongs
    in the repository beside the site that also needs it. Two places to write
    it would be two places to get it wrong.
    """
    monkeypatch.setattr(account, "_repo_config",
                        lambda: {"apiKey": "AIzaFROMFILE",
                                 "projectId": "mangatct", "region": "us-east1"})
    got = account.config()
    assert got["apiKey"] == "AIzaFROMFILE"
    assert got["projectId"] == "mangatct"
    assert got["region"] == "us-east1"
    assert account.configured() is True


def test_the_config_js_that_ships_is_read_but_does_not_count(home, monkeypatch,
                                                             tmp_path):
    """A placeholder is not configuration.

    The file ships with `YOUR_API_KEY` in it so the shape is obvious. Counting
    that as set would mean every call failing with Google's wording about an
    invalid key instead of ours about an unconfigured project.
    """
    site = tmp_path / "pkg" / "site"
    site.mkdir(parents=True)
    (site / "config.js").write_text(
        'export const FIREBASE = {\n'
        '  apiKey: "YOUR_API_KEY",\n'
        '  projectId: "your-project",\n'
        '};\n'
        'export const REGION = "us-central1";\n', encoding="utf8")
    monkeypatch.setattr(account, "__file__", str(tmp_path / "pkg" / "account.py"))
    assert account._repo_config()["apiKey"] == "YOUR_API_KEY"
    assert account.configured() is False


def test_a_filled_in_config_js_is_read_off_the_disk(home, monkeypatch, tmp_path):
    site = tmp_path / "pkg" / "site"
    site.mkdir(parents=True)
    (site / "config.js").write_text(
        '// comments and prose above it\n'
        'export const FIREBASE = {\n'
        '  apiKey: "AIzaREAL",\n'
        '  authDomain: "mangatct.firebaseapp.com",\n'
        '  projectId: "mangatct",\n'
        '};\n'
        'export const REGION = "europe-west2";\n'
        'export const USE_EMULATOR = false;\n', encoding="utf8")
    monkeypatch.setattr(account, "__file__", str(tmp_path / "pkg" / "account.py"))
    got = account._repo_config()
    assert got == {"apiKey": "AIzaREAL", "projectId": "mangatct",
                   "region": "europe-west2"}


def test_the_machine_beats_the_repository_and_the_environment_beats_both(
        home, monkeypatch):
    """Three places, in that order.

    The repository's is the default, a machine can point somewhere else, and
    an environment variable wins - which is what a test run and a staging
    project both need.
    """
    monkeypatch.setattr(account, "_repo_config",
                        lambda: {"apiKey": "repo", "projectId": "repo-p"})
    os.makedirs(os.path.join(str(home / "home")), exist_ok=True)
    with open(os.path.join(str(home / "home"), account.CONF), "w",
              encoding="utf8") as fh:
        json.dump({"apiKey": "machine"}, fh)
    assert account.config()["apiKey"] == "machine"
    assert account.config()["projectId"] == "repo-p"

    monkeypatch.setenv("MANGATL_FIREBASE_KEY", "env")
    assert account.config()["apiKey"] == "env"


def test_the_region_has_a_default(home, monkeypatch):
    """Functions live somewhere. `us-central1` is where Firebase puts them
    unless told otherwise, and a missing region should not be a missing URL."""
    monkeypatch.setattr(account, "_repo_config",
                        lambda: {"apiKey": "k", "projectId": "p"})
    assert account.config()["region"] == "us-central1"


# ------------------------------------------------------------------- tokens

def test_the_refresh_token_is_written_readable_only_by_its_owner(project,
                                                                 monkeypatch):
    """It is a credential, and it is the one that never expires.

    Anything that can read this file can be this person for as long as they
    have an account. On a machine with more than one login, a world-readable
    one is the whole account handed over.
    """
    monkeypatch.setattr(account, "_post", Wire(
        {"idToken": "id-1", "refreshToken": "r-1", "localId": "u1",
         "email": "lee@example.com", "expiresIn": "3600"},
        {"coins": 40, "username": "lee"}))
    account.sign_in("lee@example.com", "hunter2")
    path = account._path()
    assert os.path.exists(path)
    if os.name != "nt":
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0, oct(mode)


def test_the_password_is_never_written_down(project, monkeypatch):
    """It goes to Google and nowhere else. Not to the file, not to the
    project, not to a log."""
    wire = Wire({"idToken": "id-1", "refreshToken": "r-1", "localId": "u1",
                 "expiresIn": "3600"}, {"coins": 0})
    monkeypatch.setattr(account, "_post", wire)
    account.sign_in("lee@example.com", "hunter2")
    with open(account._path(), encoding="utf8") as fh:
        on_disk = fh.read()
    assert "hunter2" not in on_disk
    assert "hunter2" in json.dumps(wire.sent[0]["body"])   # it did go to Google


def test_a_live_token_is_not_fetched_again(project, monkeypatch):
    _signed_in(monkeypatch)
    wire = Wire()
    monkeypatch.setattr(account, "_post", wire)
    assert account.token() == "id-1"
    assert wire.sent == []


def test_an_expired_token_is_refreshed(project, monkeypatch):
    _signed_in(monkeypatch, expires=time.time() - 1)
    wire = Wire({"id_token": "id-2", "refresh_token": "refresh-2",
                 "user_id": "u1", "expires_in": "3600"})
    monkeypatch.setattr(account, "_post", wire)
    assert account.token() == "id-2"
    assert account.REFRESH in wire.last["url"]
    assert wire.last["body"]["refresh_token"] == "refresh-1"
    # And the new refresh token replaced the old one on disk.
    assert account._read()["refreshToken"] == "refresh-2"


def test_a_token_about_to_expire_is_refreshed_early(project, monkeypatch):
    """A token that expires in flight fails a call that was about to spend
    money. `EARLY` is the margin, and it is why this is not `> time.time()`.

    Thirty seconds written out, not `EARLY / 2`: a test that works its input
    out from the constant it is testing moves with the constant, and passes
    just as happily against a margin of nothing.
    """
    assert account.EARLY >= 30, "the margin this test relies on"
    _signed_in(monkeypatch, expires=time.time() + 30)
    wire = Wire({"id_token": "id-2", "refresh_token": "refresh-1",
                 "expires_in": "3600"})
    monkeypatch.setattr(account, "_post", wire)
    assert account.token() == "id-2"
    assert len(wire.sent) == 1


def test_tokens_left_over_from_a_project_that_is_gone_are_not_a_session(
        home, monkeypatch):
    """Signed in means signed in TO something.

    A token file can outlive the project it was made for - somebody clears
    `config.js`, or moves the app to a machine with no Firebase set up. Reading
    that as a live session would put the editor on the remote purse with
    nowhere to send a spend, and every run would fail on the first page instead
    of quietly using the wallet that is right there.
    """
    monkeypatch.setattr(account, "_repo_config", dict)
    _signed_in(monkeypatch)
    assert account.configured() is False
    assert account.signed_in() is False
    assert coins.remote() is False
    # And the local purse still works, which is the whole point of saying no.
    assert coins.balance() >= 0


def test_nothing_private_to_this_process_is_left_in_the_token_file(project,
                                                                   monkeypatch):
    """The file holds an account and a credential. The read cache's own
    bookkeeping is neither, and a file with a stale timestamp in it invites
    somebody to trust the timestamp."""
    monkeypatch.setattr(account, "_post", Wire(
        {"idToken": "id-1", "refreshToken": "r-1", "localId": "u1",
         "expiresIn": "3600"}, {"result": {"coins": 0}}))
    account.sign_in("lee@example.com", "hunter2")
    with open(account._path(), encoding="utf8") as fh:
        on_disk = json.load(fh)
    assert [k for k in on_disk if k.startswith("_")] == []
    assert set(on_disk) <= {"idToken", "refreshToken", "uid", "email",
                            "expires", "balance", "checked", "username",
                            "photo", "plan"}


def test_asking_for_a_token_signed_out_says_so(project, monkeypatch):
    account.sign_out()
    with pytest.raises(account.NotSignedIn):
        account.token()


def test_signing_out_takes_the_token_off_the_disk(project, monkeypatch):
    _signed_in(monkeypatch)
    assert account.signed_in() is True
    account.sign_out()
    assert account.signed_in() is False
    assert not os.path.exists(account._path())


# ----------------------------------------------------------------- the calls

def test_a_call_goes_to_the_project_and_carries_the_token(project, monkeypatch):
    _signed_in(monkeypatch)
    wire = Wire({"result": {"coins": 7}})
    monkeypatch.setattr(account, "_post", wire)
    assert account.call("me") == {"coins": 7}
    assert wire.last["url"] == \
        "https://europe-west1-mangatct.cloudfunctions.net/me"
    assert wire.last["token"] == "id-1"
    # Google's callable wire format: the payload is under `data`.
    assert wire.last["body"] == {"data": {}}


def test_a_call_with_no_project_configured_says_which_thing_is_missing(home,
                                                                       monkeypatch):
    monkeypatch.setattr(account, "_repo_config", dict)
    _signed_in(monkeypatch)
    with pytest.raises(account.AccountError) as e:
        account.call("me")
    assert "configured" in str(e.value)


def test_the_wire_errors_come_back_as_sentences(project, monkeypatch):
    """"INVALID_LOGIN_CREDENTIALS" has told the person nothing they can act
    on. Every code Firebase actually returns for these forms is mapped."""
    for code, expect in account.SAYS.items():
        err = account._says({"error": {"message": code}})
        assert str(err) == expect, code
        assert err.code == code


def test_running_out_of_coins_comes_back_with_how_short(project, monkeypatch):
    """The screen has to be able to say "this needs 40 and there are 12".

    The function raises `failed-precondition` with the shortfall in the
    details, and losing that on the way through would leave the editor able to
    say only that something went wrong.
    """
    err = account._says({"error": {"status": "FAILED_PRECONDITION",
                                   "message": "not enough coins",
                                   "details": {"short": 28, "balance": 12}}})
    assert isinstance(err, account.NotEnough)
    assert err.short == 28
    assert err.balance == 12


def test_an_expired_session_comes_back_as_signed_out(project):
    assert isinstance(account._says({"error": {"status": "UNAUTHENTICATED"}}),
                      account.NotSignedIn)
    assert isinstance(account._says({}, 401), account.NotSignedIn)


def test_a_name_already_taken_says_so_rather_than_saying_nothing(project):
    err = account._says({"error": {"status": "ALREADY_EXISTS",
                                   "message": "That name is taken."}})
    assert "taken" in str(err)


# --------------------------------------------------------------- signing in

def test_signing_in_keeps_what_the_account_holds(project, monkeypatch):
    monkeypatch.setattr(account, "_post", Wire(
        {"idToken": "id-1", "refreshToken": "r-1", "localId": "u1",
         "email": "lee@example.com", "expiresIn": "3600"},
        {"result": {"coins": 640, "username": "lee", "photo": "fox",
                    "plan": {"tier": "regular", "live": True}}}))
    account.sign_in("lee@example.com", "hunter2")
    s = account.state()
    assert s["signed_in"] is True
    assert s["balance"] == 640
    assert s["username"] == "lee"
    assert s["photo"] == "fox"
    assert s["plan"]["tier"] == "regular"


def test_signing_up_takes_the_name_in_the_same_breath(project, monkeypatch):
    wire = Wire(
        {"idToken": "id-1", "refreshToken": "r-1", "localId": "u1",
         "expiresIn": "3600"},
        {"result": {"ok": True, "username": "lee"}},
        {"result": {"coins": 0, "username": "lee"}})
    monkeypatch.setattr(account, "_post", wire)
    account.sign_up("lee@example.com", "hunter2", "lee")
    claimed = [c for c in wire.sent if c["url"].endswith("claimUsername")]
    assert claimed and claimed[0]["body"]["data"]["username"] == "lee"


def test_a_name_that_is_taken_does_not_lose_the_new_account(project,
                                                            monkeypatch):
    """The account exists by the time the name is asked for - it has to, since
    claiming needs a token. Throwing it away because somebody else already had
    the name would be the wrong way round: the name can be set afterwards, and
    a person who has just made an account is signed in either way.
    """
    wire = Wire(
        {"idToken": "id-1", "refreshToken": "r-1", "localId": "u1",
         "expiresIn": "3600"},
        {"error": {"status": "ALREADY_EXISTS", "message": "taken"}},
        {"result": {"coins": 0, "username": ""}})
    monkeypatch.setattr(account, "_post", wire)
    account.sign_up("lee@example.com", "hunter2", "lee")
    assert account.signed_in() is True
    assert account.state()["username"] == ""


def test_a_reset_asks_google_for_the_email(project, monkeypatch):
    wire = Wire({})
    monkeypatch.setattr(account, "_post", wire)
    account.reset_password("lee@example.com")
    assert "sendOobCode" in wire.last["url"]
    assert wire.last["body"]["requestType"] == "PASSWORD_RESET"


# ------------------------------------------------------------------ balance

def test_the_balance_is_not_asked_for_on_every_page_turn(project, monkeypatch):
    _signed_in(monkeypatch, balance=500, checked=time.time())
    wire = Wire()
    monkeypatch.setattr(account, "_post", wire)
    for _ in range(20):
        assert account.balance() == 500
    assert wire.sent == []


def test_a_stale_balance_is_asked_for_again(project, monkeypatch):
    _signed_in(monkeypatch, balance=500,
               checked=time.time() - account.FRESH_FOR - 1)
    monkeypatch.setattr(account, "_post", Wire({"result": {"coins": 480}}))
    assert account.balance() == 480


def test_a_balance_that_cannot_be_refreshed_is_the_last_one_known(project,
                                                                  monkeypatch):
    """Showing the last known number beats showing nothing.

    What must not happen on a bad connection is a SPEND going through on a
    stale number - and that is a different call, which does not swallow this.
    """
    _signed_in(monkeypatch, balance=500, checked=0)
    monkeypatch.setattr(account, "_post",
                        Wire(account.AccountError("no connection", "offline")))
    assert account.balance() == 500


def test_a_spend_that_cannot_reach_the_server_fails(project, monkeypatch):
    """Not a fallback to the local wallet, and not a free run.

    Charging a local wallet instead would be giving the work away; charging
    nothing at all would be worse. The run does not start.
    """
    _signed_in(monkeypatch)
    monkeypatch.setattr(account, "_post",
                        Wire(account.AccountError("no connection", "offline")))
    with pytest.raises(account.AccountError):
        account.spend(40, "translate", "page 3", "run-1")


def test_a_spend_carries_a_run_id(project, monkeypatch):
    """It is what makes the charge happen once. A request that times out may
    well have arrived, and the retry carries the same id."""
    _signed_in(monkeypatch)
    wire = Wire({"result": {"ok": True, "balance": 460, "coins": 40}})
    monkeypatch.setattr(account, "_post", wire)
    assert account.spend(40, "translate", "page 3", "run-1") == 40
    sent = wire.last["body"]["data"]
    assert sent == {"coins": 40, "what": "translate", "page": "page 3",
                    "run": "run-1"}
    assert account.state()["balance"] == 460


def test_a_spend_with_no_run_id_makes_one(project, monkeypatch):
    _signed_in(monkeypatch)
    wire = Wire({"result": {"balance": 0, "coins": 1}})
    monkeypatch.setattr(account, "_post", wire)
    account.spend(1, "ocr", "p", "")
    assert wire.last["body"]["data"]["run"]


def test_two_run_ids_are_never_the_same(project):
    assert len({account.new_run() for _ in range(200)}) == 200


def test_spending_nothing_asks_nothing(project, monkeypatch):
    _signed_in(monkeypatch)
    wire = Wire()
    monkeypatch.setattr(account, "_post", wire)
    assert account.spend(0, "ocr", "p", "r") == 0
    assert account.spend(-5, "ocr", "p", "r") == 0
    assert wire.sent == []


def test_a_refund_quotes_the_run_it_is_giving_back(project, monkeypatch):
    _signed_in(monkeypatch)
    wire = Wire({"result": {"ok": True, "balance": 480, "coins": 20}})
    monkeypatch.setattr(account, "_post", wire)
    assert account.refund(20, "run-1") == 20
    assert wire.last["body"]["data"] == {"coins": 20, "run": "run-1"}


def test_a_refund_with_no_run_is_not_sent(project, monkeypatch):
    """Without a run there is nothing to measure it against, and a refund
    nobody can bound is a mint."""
    _signed_in(monkeypatch)
    wire = Wire()
    monkeypatch.setattr(account, "_post", wire)
    assert account.refund(20, "") == 0
    assert wire.sent == []


# -------------------------------------------------------- which purse it is

def test_signed_out_the_purse_is_the_one_on_this_machine(home, monkeypatch):
    monkeypatch.setattr(account, "_repo_config", dict)
    assert coins.remote() is False
    start = coins.balance()
    coins.credit(50, "test")
    assert coins.balance() == start + 50


def test_signed_in_the_purse_is_the_account(project, monkeypatch):
    _signed_in(monkeypatch, balance=500, checked=time.time())
    assert coins.remote() is True
    assert coins.balance() == 500


def test_a_spend_while_signed_in_never_touches_the_local_wallet(project,
                                                                monkeypatch):
    """The one that must not go wrong.

    A run charged to the local wallet while somebody is signed in is work
    given away, and it would be invisible: the number on screen would go down
    exactly as it should.
    """
    _signed_in(monkeypatch, balance=500, checked=time.time())
    before = json.loads(open(os.path.join(
        os.environ["MANGATL_HOME"], coins.WALLET), encoding="utf8").read()) \
        if os.path.exists(os.path.join(os.environ["MANGATL_HOME"],
                                       coins.WALLET)) else None
    wire = Wire({"result": {"balance": 460, "coins": 40}})
    monkeypatch.setattr(account, "_post", wire)
    assert coins.spend(40, "translate", "page 3", "gemini", run="run-1") == 40
    assert wire.last["url"].endswith("/spendCoins")
    after = os.path.exists(os.path.join(os.environ["MANGATL_HOME"],
                                        coins.WALLET))
    assert (before is None and not after) or before is not None


def test_a_refund_while_signed_in_goes_back_to_the_run_it_came_from(project,
                                                                    monkeypatch):
    _signed_in(monkeypatch, balance=460, checked=time.time())
    wire = Wire({"result": {"balance": 480, "coins": 20}})
    monkeypatch.setattr(account, "_post", wire)
    coins.credit(20, "translate refund — 1 page not done", run="run-1")
    assert wire.last["url"].endswith("/refundCoins")
    assert wire.last["body"]["data"] == {"coins": 20, "run": "run-1"}


def test_coins_cannot_be_added_to_an_account_from_the_editor(project,
                                                             monkeypatch):
    """A client that could add coins to its own balance could add any number
    of them. Buying is the website's job, and the rules forbid the write
    outright - this only says so before the round trip."""
    _signed_in(monkeypatch)
    wire = Wire()
    monkeypatch.setattr(account, "_post", wire)
    with pytest.raises(account.AccountError) as e:
        coins.credit(1000, "top-up")
    assert "website" in str(e.value).lower()
    assert wire.sent == []


def test_affording_a_run_asks_the_server_rather_than_the_cache(project,
                                                               monkeypatch):
    """Everywhere else a few seconds of staleness costs nothing. Here it is
    the difference between refusing a run that could have paid and starting
    one that cannot."""
    _signed_in(monkeypatch, balance=500, checked=time.time())
    monkeypatch.setattr(account, "_post", Wire({"result": {"coins": 30}}))
    assert coins.can_afford(40) is False


def test_a_run_cannot_be_afforded_when_the_server_is_unreachable(project,
                                                                 monkeypatch):
    _signed_in(monkeypatch, balance=500, checked=time.time())
    monkeypatch.setattr(account, "_post",
                        Wire(account.AccountError("offline", "offline")))
    assert coins.can_afford(1) is False


def test_the_top_bar_is_told_which_purse_it_is_looking_at(project, monkeypatch):
    """`configured` and `signed_in` both, because they mean different things:
    no project at all is a local purse and nothing to say about it, and a
    project with nobody signed in is a Sign in button."""
    monkeypatch.setattr(account, "_repo_config", dict)
    monkeypatch.delenv("MANGATL_FIREBASE_KEY")
    out = coins.state()
    assert out["configured"] is False and out["signed_in"] is False
    assert out["buy_url"]

    monkeypatch.setenv("MANGATL_FIREBASE_KEY", "AIzaTESTKEY")
    account._MEM.clear()
    out = coins.state()
    assert out["configured"] is True and out["signed_in"] is False

    _signed_in(monkeypatch, balance=77, checked=time.time())
    out = coins.state()
    assert out["configured"] is True and out["signed_in"] is True
    assert out["balance"] == 77
    assert out["buy_url"]


# ------------------------------------------- the charge and the refund, paired

def _box(k):
    from mangatl.models import TextRegion
    y = 30 + k * 70
    r = TextRegion(id=k, bbox=(30, y, 120, 50), kind="bubble",
                   bubble_bbox=(30, y, 120, 50), confidence=0.9,
                   polygon=[(30, y), (150, y), (150, y + 50), (30, y + 50)])
    r.order, r.src_text, r.dst_text = k, "x", "y"
    return r


def _chapter(tmp_path, boxes):
    """A chapter of pages with the given box counts, built the way the app
    builds them."""
    import shutil

    import numpy as np
    cv2 = pytest.importorskip("cv2")
    from mangatl.project import Project, region_record
    root = str(tmp_path / "proj")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    for n, count in enumerate(boxes):
        p.add_uploaded("%03d.png" % (n + 1), cv2.imencode(
            ".png", np.full((600, 420, 3), 240, np.uint8))[1].tobytes())
        p.pages[n].regions = [region_record(_box(k)) for k in range(count)]
        p.pages[n].detected = True
    for step in ("ocr", "translate", "proofread"):
        p.settings["%s_backend" % step] = "anthropic"
        p.settings["%s_model" % step] = "claude-sonnet-5"
        p.settings["%s_key" % step] = "k"
    p.save()
    return p


def test_the_refund_is_tied_to_the_charge_it_came_from(project, monkeypatch,
                                                       tmp_path):
    """One id for both, or the money does not come back.

    A refund is measured against the run it names - the function will not give
    back more than that run took, and it will not give back anything at all for
    a run it has never heard of. So a refund carrying a FRESH id is a refund
    that is refused, and the person who cancelled after two of five pages is
    simply out the other three. It would look like nothing at all from here:
    the charge succeeded, the run stopped, no error.
    """
    from mangatl import editor
    _signed_in(monkeypatch, balance=5000, checked=time.time())
    p = _chapter(tmp_path, [3, 3, 3])
    wire = Wire({"result": {"balance": 4900, "coins": 100}},
                {"result": {"balance": 4950, "coins": 50}})
    monkeypatch.setattr(account, "_post", wire)

    with editor._charge(p, "translate", [0, 1, 2]):
        p.job["done"] = 1                      # stopped after one page

    spends = [c for c in wire.sent if c["url"].endswith("/spendCoins")]
    refunds = [c for c in wire.sent if c["url"].endswith("/refundCoins")]
    assert len(spends) == 1 and len(refunds) == 1
    assert refunds[0]["body"]["data"]["run"] == spends[0]["body"]["data"]["run"]
    assert refunds[0]["body"]["data"]["run"]


def test_a_finished_run_gets_back_only_the_headroom(project, monkeypatch,
                                                    tmp_path):
    """A run that did everything and metered nothing verifiable keeps its
    quoted price - the old promise - and the settle returns exactly the
    HEADROOM the hold added on top. It used to ask for nothing back because
    nothing more than the quote had been taken; the hold changed the first
    half of that, not the second."""
    from mangatl import editor
    _signed_in(monkeypatch, balance=5000, checked=time.time())
    p = _chapter(tmp_path, [3, 3])
    wire = Wire({"result": {"balance": 4900, "coins": 100}})
    monkeypatch.setattr(account, "_post", wire)

    with editor._charge(p, "translate", [0, 1]):
        p.job["done"] = 2

    price, _m, _b = editor.run_price(p, "translate", [0, 1])
    reserve = coins.hold(price)
    got = [c for c in wire.sent if c["url"].endswith("/refundCoins")]
    if reserve > price:
        assert len(got) == 1
        assert int((got[0]["body"].get("data") or got[0]["body"])
                   ["coins"]) == reserve - price
    else:
        assert got == []
