"""The privacy page says what the code does.

lee: *"wriet teh rpivacy page"*. Google asks for one before it shows the
MangaTCT name on its sign-in screen. A privacy page that drifts from the code
is worse than none - it is a promise nobody is keeping - so the parts that can
be checked against the code are checked here.
"""
import re

from where import PKG
from mangatl import version as V

SITE = PKG / "site"
PAGE = (SITE / "privacy.html").read_text(encoding="utf-8")


def test_there_is_a_privacy_page_and_the_home_page_links_to_it():
    assert "<title>Privacy | MangaTCT</title>" in PAGE
    build = (SITE / "build.py").read_text(encoding="utf-8")
    assert '<a href="privacy.html">Privacy</a>' in build, "Google looks for it from the home page"
    for name in ("license.html", "download.html"):
        assert 'href="privacy.html"' in (SITE / name).read_text(encoding="utf-8"), name


def test_the_contact_is_the_apps_own_address():
    assert V.SUPPORT["email"] and ("mailto:" + V.SUPPORT["email"]) in PAGE


def test_no_analytics_is_said_and_is_true():
    assert "No analytics" in PAGE
    for p in list(SITE.glob("*.html")) + list(SITE.glob("*.js")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        assert not re.search(r"googletagmanager|gtag\(|getAnalytics|google-analytics", text), p.name


def test_what_it_says_about_the_account_matches_the_account_service():
    fn = (PKG / "firebase" / "functions" / "index.js").read_text(encoding="utf-8")
    # the sign-in hand-off: ten minutes, and deleted when collected
    assert "at most ten minutes" in PAGE and "HAND_FOR_MS = 10 * 60 * 1000" in fn
    assert "tx.delete(handRef(challenge))" in fn
    # free coins: an address is remembered as a hash, not as itself
    assert "one-way hash" in PAGE and "createHash('sha256')" in fn and "welcomed/" in fn
    # the relay logs what it did, never what it carried
    log = fn[fn.index("console.log(JSON.stringify({ relay:"):]
    log = log[:log.index("}));")]
    assert "body" not in log and "and not the content" in PAGE
    # no pictures to pick any more, so none is promised
    assert "picture you pick" not in PAGE


def test_what_it_says_about_deleting_matches_the_account_service():
    flat = " ".join(PAGE.split())
    assert "Delete your account on your account page on this website" in flat
    assert "cannot be undone" in flat
    assert "the one-way hash that says an address has had its free coins" in flat
    assert "email us from the address" not in flat, "there is a button now"
    fn = (PKG / "firebase" / "functions" / "index.js").read_text(encoding="utf-8")
    body = fn[fn.index("export const deleteAccount = onCall("):]
    assert "db.recursiveDelete(userRef(uid))" in body and "getAuth().deleteUser(uid)" in body
