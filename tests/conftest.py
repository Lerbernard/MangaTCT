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
