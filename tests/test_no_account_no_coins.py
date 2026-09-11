"""No account, no coins.

lee: *"i notice that i keep my coins from the debugging phase"* — 990 coins on
the installed copy's pill, left in `wallet.json` by a month of testing — and
then, plainer: *"the coins should only be linked to an account, so no account
= no coins"*.

`wallet.json` was the purse whenever nobody was signed in. Now it is a purse
in exactly two cases: no Firebase project configured at all (a checkout with
no billing behind it) or `MANGATL_TEST_PURSE` set on the machine (the
developer). An installed copy that is signed out has nothing: a balance of 0,
`can_afford` false, no way in for a credit, a run that says to sign in, and a
coin in the header that reads "Sign in" and opens the sign-in form.
"""
import json
import os
import re

import pytest

from where import PKG
from mangatl import account, coins, editor
from mangatl.project import Project

JS = (PKG / "static" / "js" / "coins.js").read_text(encoding="utf-8")


@pytest.fixture
def installed_signed_out(monkeypatch, tmp_path):
    """An installed copy: Firebase configured, nobody signed in, no test
    purse - and a wallet.json full of debugging coins lying there."""
    monkeypatch.delenv(coins.TEST_PURSE, raising=False)
    monkeypatch.setattr(account, "configured", lambda: True)
    monkeypatch.setattr(account, "signed_in", lambda: False)
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path))
    with open(tmp_path / coins.WALLET, "w") as fh:
        json.dump({"balance": 990, "ledger": []}, fh)
    return tmp_path


def test_signed_out_on_an_installed_copy_there_is_no_purse(installed_signed_out):
    assert coins.local_purse() is False and coins.needs_signin() is True
    assert coins.balance() == 0, "the 990 debugging coins are nobody's"
    assert coins.ledger() == []
    assert coins.can_afford(1) is False
    assert coins.spend(5, "ai") == 0
    with pytest.raises(account.AccountError):
        coins.credit(100)
    s = coins.state()
    assert s["balance"] == 0 and s["needs_signin"] is True and s["signed_in"] is False
    assert s["can_top_up"] is False
    # ...and the file was not touched, in case it is a developer's after all
    assert json.load(open(installed_signed_out / coins.WALLET))["balance"] == 990


def test_the_test_purse_and_a_checkout_still_have_the_local_wallet(monkeypatch, tmp_path):
    monkeypatch.setattr(account, "signed_in", lambda: False)
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path))
    with open(tmp_path / coins.WALLET, "w") as fh:
        json.dump({"balance": 42, "ledger": []}, fh)
    # the developer's switch
    monkeypatch.setattr(account, "configured", lambda: True)
    monkeypatch.setenv(coins.TEST_PURSE, "1")
    assert coins.local_purse() and coins.balance() == 42 and not coins.needs_signin()
    assert "needs_signin" not in coins.state()
    # a checkout with no billing configured
    monkeypatch.delenv(coins.TEST_PURSE, raising=False)
    monkeypatch.setattr(account, "configured", lambda: False)
    assert coins.local_purse() and coins.balance() == 42 and not coins.needs_signin()


def test_signed_in_the_purse_is_the_account_whatever_the_file_says(monkeypatch, tmp_path):
    monkeypatch.delenv(coins.TEST_PURSE, raising=False)
    monkeypatch.setattr(account, "configured", lambda: True)
    monkeypatch.setattr(account, "signed_in", lambda: True)
    monkeypatch.setattr(account, "balance", lambda fresh=False: 7)
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path))
    with open(tmp_path / coins.WALLET, "w") as fh:
        json.dump({"balance": 990, "ledger": []}, fh)
    assert coins.balance() == 7 and not coins.needs_signin()
    assert coins.can_afford(7) and not coins.can_afford(8)


def test_a_run_that_costs_something_says_to_sign_in(installed_signed_out, monkeypatch):
    p = Project(None, str(installed_signed_out / "out"))
    monkeypatch.setattr(editor, "run_price", lambda p, step, idx: (12, "m", "gemini"))
    why = editor.afford_run(p, "translate", [0])
    assert "Sign in" in why and "account" in why, why
    # a free run - a local model, nothing to pay - is not stopped
    monkeypatch.setattr(editor, "run_price", lambda p, step, idx: (0, "m", "ollama"))
    assert editor.afford_run(p, "translate", [0]) == ""


def test_the_pill_says_sign_in_and_opens_the_form():
    body = JS[JS.index("function paintCount("):JS.index("function paintCoins(")]
    assert "wallet.needs_signin" in body and "'Sign in'" in body
    assert "remove('broke','low')" in body, "not red: nothing is wrong, nobody is in"
    draw = JS[JS.index("function drawWallet("):JS.index("function topUpRow(")]
    assert "if(w.needs_signin){ walletSignIn(false); return; }" in draw
    assert "function walletSignIn(making, host)" in JS, "the form it opens"


def test_the_suite_itself_runs_on_the_test_purse():
    """conftest sets the developer's switch, so every other test that presses
    a priced button spends the throwaway wallet, as it always did."""
    assert os.environ.get(coins.TEST_PURSE) == "1"
    src = (PKG / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("MANGATL_TEST_PURSE", "1")' in src


def test_settings_has_an_account_page_with_the_same_form():
    """lee: *"there isn't a place to sign in in the app"*. Settings > Account:
    the sign-in form when nobody is, who and how many coins when somebody
    is, Buy coins and Sign out."""
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert re.search(r'<button class="setnav-btn" data-sec="account"[^>]*>Account</button>', html)
    assert 'data-sec="account"' in html and 'id="acctBox"' in html
    assert "function renderAccount(" in JS
    body = JS[JS.index("function renderAccount("):]
    assert "walletSignIn(false, box)" in body, "the same form, drawn into the page"
    assert "buyCoins()" in body and "walletSignOut()" in body
    view = (PKG / "static" / "js" / "view.js").read_text(encoding="utf-8")
    assert "if(name==='account'" in view
    # ...and the form's own buttons keep drawing where they were drawn
    assert "this.closest('#acctBox')" in JS


def test_buying_coins_goes_to_a_page_that_exists():
    """`/coins` was Firebase's own Page Not Found (lee's screenshot). The app
    links the pricing page, and hosting sends `/coins` there for app versions
    that still say it."""
    import json as _json
    assert coins.BUY_URL == "https://mangatct.com/pricing"
    assert (PKG / "site" / "pricing.html").exists()
    fb = _json.loads((PKG / "firebase.json").read_text(encoding="utf-8"))
    assert {"source": "/coins", "destination": "/pricing", "type": 301} in fb["hosting"]["redirects"]
