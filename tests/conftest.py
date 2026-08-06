"""Run-wide setup.

`browserpool` starts one Chromium per test process on first use and the hook
below closes it when the run ends, so a run never leaves a browser behind.
With xdist each worker is its own process and so has its own browser and its
own hook — which is the point, and why the pool is a module global rather than
a fixture.

And the other thing: **the suite must never touch the real `~/.mangatl`.**
That folder holds the person's uploaded fonts and their TCT Coins, and both
are things a test can spend. A run that used the real home would drain a real
purse a few coins at a time and, eventually, start failing on a machine that
had simply run out — a test suite that fails because of something that
happened in a previous run is worse than no suite. Set at import, before
anything reads it, and only as a DEFAULT so a test that wants to point
somewhere of its own still can.
"""
import os
import tempfile

os.environ.setdefault("MANGATL_HOME", os.path.join(
    tempfile.gettempdir(),
    "mangatl-test-home-%s" % (os.environ.get("PYTEST_XDIST_WORKER") or "solo")))

import pytest  # noqa: E402

import browserpool  # noqa: E402  (after the home is pointed somewhere safe)


def pytest_sessionfinish(session, exitstatus):
    browserpool.shutdown()


@pytest.fixture(autouse=True)
def cold_model_menu():
    """Every test starts with the menu cache empty, the way a fresh editor does.

    `editor._MENU_CACHE` remembers what a provider said a key could reach, for
    fifteen minutes, keyed on (address, key hash). That is right for the app —
    one person, one process, and Settings asks three times in a row — and wrong
    for a suite, where the next test is a different world with the same key in
    it and would be handed the last test's answer.
    """
    from mangatl import editor
    editor._MENU_CACHE.clear()
    yield
    editor._MENU_CACHE.clear()
