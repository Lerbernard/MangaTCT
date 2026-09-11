"""Run-wide setup.

`browserpool` starts one Chromium per test process on first use and the hook
below closes it when the run ends, so a run never leaves a browser behind.
With xdist each worker is its own process and so has its own browser and its
own hook - which is the point, and why the pool is a module global rather than
a fixture.

And the other thing: **the suite must never touch the real `~/.mangatl`.**
That folder holds the person's uploaded fonts and their TCT Coins, and both
are things a test can spend. A run that used the real home would drain a real
purse a few coins at a time and, eventually, start failing on a machine that
had simply run out - a test suite that fails because of something that
happened in a previous run is worse than no suite. Set at import, before
anything reads it, and only as a DEFAULT so a test that wants to point
somewhere of its own still can.

And then it happened anyway, one level in. `gettempdir()` is the same path
every time, so the fake home is not a fresh home - it is a home that has been
accumulating since the first run on the machine. The purse in it went 1000 ->
0 over **400 ledger entries, 396 of them `clean`**, and after that every test
that presses Clean got HTTP 402 out of the app's own server. That is not the
hosted cleaner refusing anything and not a flake; it is the previous run's
spending, which is the exact thing the paragraph above says must not be able
to happen. So the purse is emptied at the start of each run rather than
inherited - but only when WE chose the path. A home somebody pointed at
deliberately is theirs, and a suite that deletes a wallet it was handed is a
worse bug than the one it is fixing.
"""
import os
import tempfile
import time

_OURS = "MANGATL_HOME" not in os.environ

# When this worker started, so a test can ask whether anything in the purse is
# older than the run it is part of. See `test_the_purse_the_suite_spends.py`.
os.environ.setdefault("MANGATL_TEST_RUN_AT", str(int(time.time())))

os.environ.setdefault("MANGATL_HOME", os.path.join(
    tempfile.gettempdir(),
    "mangatl-test-home-%s" % (os.environ.get("PYTEST_XDIST_WORKER") or "solo")))

if _OURS:
    try:
        os.remove(os.path.join(os.environ["MANGATL_HOME"], "wallet.json"))
    except OSError:
        pass    # never written, or already gone. Either is a fresh purse.

# ...and the same argument for the KEYS. `userdata.env_key` answers out of a
# `.env`, and `editor.key_for` puts that answer ABOVE the project's own - so a
# real `.env` on the machine running the suite would hand a live key to every
# test that asserts a project has none, and a test asserting a project HAS a
# particular key would pass for the wrong reason.
#
# Pointed at a path inside the same throwaway home rather than at nothing,
# because "" falls back to `~/.mangatl/.env`, which is the file being avoided.
# A test that wants a `.env` writes this one.
os.environ.setdefault("MANGATL_ENV",
                      os.path.join(os.environ["MANGATL_HOME"], "test.env"))
for _n in ("MANGATL_ANTHROPIC_KEY", "MANGATL_GEMINI_KEY",
           "MANGATL_OPENROUTER_KEY", "MANGATL_CLEAN_TOKEN"):
    os.environ.pop(_n, None)     # the other half: our own names, exported

if _OURS:
    try:
        os.remove(os.environ["MANGATL_ENV"])
    except OSError:
        pass    # a `.env` a previous run left behind is a key this one keeps

# ...and the PURSE. On an installed copy, signed out, there is no purse at
# all: coins live on the account or nowhere (lee: *"no account = no coins"*).
# The suite is neither signed in nor a customer; it is the developer's
# machine, and the local test purse is the one it spends - the same switch a
# person running from source flips. A test about the signed-out installed
# state takes the switch away again with monkeypatch.
os.environ.setdefault("MANGATL_TEST_PURSE", "1")

import pytest  # noqa: E402

import browserpool  # noqa: E402  (after the home is pointed somewhere safe)


def pytest_sessionfinish(session, exitstatus):
    browserpool.shutdown()


@pytest.fixture(autouse=True)
def cold_caches():
    """Every test starts the way a freshly opened editor does.

    Three module globals survive between tests in one worker, and each is right
    for the app and wrong for a suite:

    * `_MENU_CACHE` - what a provider said a key could reach, for fifteen
      minutes. The next test is a different world with the same key in it and
      would be handed the last test's answer.
    * `_plate_cache` - the cleaned plate per page. A page cleaned in one test
      is a page the next one does not pay to clean, and the flat fee is charged
      where the plate is BUILT, so a leaked plate is a charge that goes missing
      - or, in the other order, one that arrives twice.
    * the cleaning warning - a complaint about a provider that answered a
      previous test.

    Individual tests were clearing these by hand, which works right up until
    the test that needed it and did not know. Doing it here means an
    order-dependent failure cannot be written in the first place.
    """
    from mangatl import editor

    def cold():
        editor._MENU_CACHE.clear()
        editor._plate_cache.clear()
        editor.clear_clean_warning()
    cold()
    yield
    cold()
