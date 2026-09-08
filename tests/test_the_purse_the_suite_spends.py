"""The eight tests that failed for a reason that was not in the code.

For days the run finished with the same eight red: three in `test_clean_routing`,
four in `test_clean_says_when_it_fails`, one in `test_your_own_cleaned_page`,
every one of them `HTTP Error 402: Payment Required`. Eight is a tidy number and
they were always the same eight, so they got a name - "the known 402 set" - and
a name is most of the way to being ignored. lee: *"try now"*.

They were not the hosted cleaner refusing anything. The 402 came out of the
app's own server on 127.0.0.1, which is the app saying **the purse is empty**,
and it was:

    /tmp/mangatl-test-home-solo/wallet.json
    balance 0, ledger 400 entries, 396 of them `clean`
    first spend 2026-08-19, last spend 2026-08-25

`conftest` points `MANGATL_HOME` at a temp folder so the suite can never spend
the real one, and its docstring says why: *"a test suite that fails because of
something that happened in a previous run is worse than no suite"*. But
`gettempdir()` is the same path on every run. The fake home was never a fresh
home - it was one folder collecting every coin every run had ever spent, and
after four hundred of them the suite failed for exactly the reason its own
setup was written to prevent, one level further in.

The fix is one line in `conftest` (delete the wallet at import, only when the
suite chose the path). This file is the part that makes it stay fixed, because
the failure mode is not "the wallet is missing" - it is "the wallet is
inherited", and the only visible difference between an inherited purse and a
spent-this-run one is WHEN the coins went.
"""
import json
import os

from mangatl import coins


def test_the_suite_is_not_spending_the_real_purse():
    """The first guard, restated where it can be seen. Everything below is
    about the second."""
    home = os.environ.get("MANGATL_HOME") or ""
    assert home, "MANGATL_HOME is unset - the suite is on the real home"
    assert "test" in os.path.basename(home), home
    assert os.path.expanduser("~") not in os.path.dirname(home) or "tmp" in home


def test_nothing_in_the_purse_was_spent_before_this_run_began():
    """The whole of the bug in one assertion.

    A drained purse and a busy one look identical from the balance; what tells
    them apart is a spend dated before the run started. There should not be
    one, because this run's purse did not exist before this run.
    """
    started = int(os.environ["MANGATL_TEST_RUN_AT"])
    try:
        with open(coins._path(), encoding="utf8") as fh:
            ledger = (json.load(fh) or {}).get("ledger") or []
    except OSError:
        return          # nothing has spent yet; there is nothing to inherit
    old = [e for e in ledger
           if e.get("kind") == "spend" and int(e.get("at") or 0) < started - 5]
    assert not old, (
        "%d spends in this run's purse are older than this run - the test home "
        "is being inherited, and the suite will start failing on 402 once it "
        "has spent %d coins across runs: %r"
        % (len(old), coins.WELCOME, old[:3]))


def test_a_run_that_starts_with_an_empty_purse_is_the_failure_being_guarded():
    """Proof the 402 really is what an empty purse does, so the assertion above
    is guarding the thing it claims to guard and not a coincidence. The 402 is
    `afford_run` refusing before anything starts - the whole price of a run is
    taken up front - so an empty purse is a run that never begins."""
    assert coins.WELCOME > 0
    where = coins._path()
    keep = None
    if os.path.exists(where):
        with open(where, encoding="utf8") as fh:
            keep = fh.read()
    try:
        with open(where, "w", encoding="utf8") as fh:
            json.dump({"balance": 0, "ledger": []}, fh)
        assert coins.balance() == 0
        assert not coins.can_afford(1), \
            "an empty purse can still afford a page, so the 402 came from " \
            "somewhere else and this whole file is chasing the wrong thing"
    finally:
        if keep is None:
            os.remove(where)
        else:
            with open(where, "w", encoding="utf8") as fh:
                fh.write(keep)


def test_a_home_somebody_handed_the_suite_is_left_alone():
    """The fix deletes a wallet, so it has to be sure whose wallet it is. A run
    told where to put its home was told by a person, and a suite that deletes a
    file it was handed is a worse bug than the one it is fixing."""
    src = (open(os.path.join(os.path.dirname(__file__), "conftest.py"),
                encoding="utf8").read())
    assert "_OURS" in src, "the removal is unguarded"
    i = src.index("if _OURS:")
    j = src.index("os.remove", i)
    assert j > i and (j - i) < 200, \
        "the wallet is removed outside the `_OURS` guard"


def test_and_the_purse_is_topped_up_before_anything_reads_it():
    """At import, not in a fixture. `coins` is read by module-level code in
    more than one place and the first read is the one that matters."""
    src = (open(os.path.join(os.path.dirname(__file__), "conftest.py"),
                encoding="utf8").read())
    assert src.index("os.remove") < src.index("import pytest"), \
        "the wallet is cleared after pytest is imported, which is too late"
