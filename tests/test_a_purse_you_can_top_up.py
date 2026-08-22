"""Putting coins in from the editor, which is a testing purse and says so.

lee, mid-chapter: *"i ran out of coins to test stuff"*, and then *"just add
coins to the editor not teh website"*.

`account.py` opens with "the editor never writes a balance", and it means it:
the editor runs on the CUSTOMER'S machine, so anything it can do they can do.
A Top up button on a screen is a Top up button on their screen.

So the button exists and is behind `MANGATL_TEST_PURSE`, set on the machine
the editor runs on. That is not a hole in the rule: whoever can set an
environment variable there could edit the purse file with a text editor. And
it tops up the LOCAL purse only - on an account it never draws at all, because
the balance lives behind a Cloud Function and the only thing that adds to it
is a payment.
"""
import os

import pytest

from mangatl import coins


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(coins.TEST_PURSE, raising=False)


def test_off_by_default(monkeypatch):
    monkeypatch.setattr(coins, "remote", lambda: False)
    assert coins.can_top_up() is False


def test_on_with_the_variable_set(monkeypatch):
    monkeypatch.setattr(coins, "remote", lambda: False)
    monkeypatch.setenv(coins.TEST_PURSE, "1")
    assert coins.can_top_up() is True


def test_never_on_an_account_however_it_is_set(monkeypatch):
    """The one that matters. An account's balance is not this machine's to
    write, and a button that always failed would be worse than no button."""
    monkeypatch.setattr(coins, "remote", lambda: True)
    monkeypatch.setenv(coins.TEST_PURSE, "1")
    assert coins.can_top_up() is False


def test_the_screen_is_told(monkeypatch):
    monkeypatch.setattr(coins, "remote", lambda: False)
    monkeypatch.setenv(coins.TEST_PURSE, "1")
    assert coins.state()["can_top_up"] is True


def test_and_told_no_on_an_account(monkeypatch):
    monkeypatch.setattr(coins, "remote", lambda: True)
    monkeypatch.setenv(coins.TEST_PURSE, "1")
    monkeypatch.setattr(coins.account, "state",
                        lambda: {"balance": 12, "signed_in": True})
    assert coins.state()["can_top_up"] is False


def test_the_button_is_drawn_only_when_it_is_allowed():
    from pathlib import Path
    js = (Path(coins.__file__).parent / "static" / "js" / "coins.js").read_text(
        encoding="utf-8")
    assert "function topUpRow(w)" in js
    assert "if(!w.can_top_up) return ''" in js, \
        "a button that a customer can see is a button a customer can press"
    assert "topUp(" in js and "/api/coins" in js


def test_the_route_it_presses_already_refuses_an_account():
    """It always did - this only adds the button. The check is on the server
    as well as in the drawing, because the drawing runs on their machine."""
    import inspect

    from mangatl import editor
    src = inspect.getsource(editor)
    i = src.index('if path == "/api/coins":', src.index("def do_POST")
                  if "def do_POST" in src else 0)
    chunk = src[i:i + 1200]
    assert "account.signed_in()" in chunk
    assert "Coins are bought on the " in chunk


def test_it_is_an_environment_variable_and_not_a_setting():
    """A setting is stored in the project, and a project travels. Somebody
    would open a downloaded one and find the till open."""
    from pathlib import Path
    src = (Path(coins.__file__).parent / "project.py").read_text(
        encoding="utf-8")
    assert "test_purse" not in src.lower()
