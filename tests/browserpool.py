"""One Chromium per test process, instead of one per test.

Every browser test used to open its own browser:

    with sync.sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(...)

A launch is around half a second of process start plus the driver handshake,
and on a loaded machine the setup for a single test was measured at seven.
Times the several hundred browser tests in here, that is most of the wall
clock of a full run - spent starting the same program over and over.

**What is shared is the browser process. What is not shared is anything a
test can see.** `new_page` on a Playwright browser makes its own context: its
own cookie jar, its own storage, its own JS heap, its own page. Two tests
sharing a browser can no more see each other than two windows of Chrome in
different profiles. `session()` closes every context a test opened, so a test
that leaves a page behind does not leave it for the next one.

lee: *"can you format the test so that only part of teh software that chnaged
gets tested and then maybe at the end of the day you do a full test"* - this
is the other half of that, the half that makes the full run cheap enough to
keep doing.
"""
import atexit
import contextlib

import pytest

_PW = None
_BR = None


def browser():
    """The process's browser, started on first use.

    Skips - rather than fails - when Chromium is not installed, which is what
    every one of these tests did for itself before.
    """
    global _PW, _BR
    if _BR is not None:
        return _BR
    sync = pytest.importorskip("playwright.sync_api")
    try:
        if _PW is None:
            _PW = sync.sync_playwright().start()
        _BR = _PW.chromium.launch()
    except Exception as e:                      # pragma: no cover - env
        pytest.skip(f"chromium unavailable: {e}")
    return _BR


# What the editor has to have done before a test can ask it anything: the
# project fetched, and the page picture decoded. Measured on this machine at
# ~250ms from `goto`, against the flat 1200–2000ms every test used to sleep
# instead - there was nothing to wait FOR when they were written, so they
# waited long enough and moved on. Three quarters of a full run was that.
READY = """() => {
  const i = document.getElementById('img');
  // A project with no pages has an <img> with nothing in it, and it will
  // never load — that is the New-project screen, and it is ready the moment
  // the project itself has arrived.
  const drawn = !i || !i.getAttribute('src')
             || (i.complete && i.naturalWidth > 0);
  // ...and nothing else on its way. The project arriving is not the end of
  // it — the page's boxes, the fonts and the settings are their own
  // requests, and a test that sets `regions` by hand before the real ones
  // land has its work quietly thrown away when they do. That was
  // `test_every_row_is_the_same_colour`, failing two runs in three.
  //
  // Read off the browser's own record of what it fetched rather than
  // Playwright's `networkidle`, which never settles against a keep-alive
  // server: every request that has finished is in here with the time it
  // finished at, and a fifth of a second of quiet after the last one is the
  // editor having stopped asking for things.
  let last = 0;
  for (const r of performance.getEntriesByType('resource'))
    last = Math.max(last, r.responseEnd || 0);
  // ...or the machine is so busy that quiet never comes. `performance.now()`
  // is milliseconds since this page started loading, so twenty seconds in,
  // whatever is still trickling is not what the test is waiting for — and
  // failing the run over it turns a slow machine into a red suite.
  const quiet = performance.now() - last > 200 || performance.now() > 20000;
  return typeof proj !== 'undefined' && !!proj && Array.isArray(proj.pages)
      && drawn && quiet;
}"""


def ready(pg, timeout=30000):
    """Wait until the editor is up, then until it has painted once.

    The fonts are part of it: a test that measures a line of typesetting before
    the face it is set in has arrived measures the fallback.
    """
    pg.wait_for_function(READY, timeout=timeout)
    pg.evaluate("() => document.fonts && document.fonts.ready")
    settled(pg)


def settled(pg):
    """Two frames - long enough for whatever was just asked for to be drawn,
    and no longer. Everything in this editor redraws on the next frame."""
    pg.evaluate("() => new Promise(r => requestAnimationFrame("
                "() => requestAnimationFrame(r)))")


def at_rest(pg, expr, timeout=5000):
    """The value of `expr` once it has stopped changing, and what it is.

    For the things that MOVE. A sleep long enough to outlast an animation is a
    guess in both directions: too short and the test reads a value mid-flight,
    too long and every run pays for it. This watches instead, frame by frame,
    and comes back the moment the value has held still for four of them.
    """
    return pg.evaluate(
        """([expr, timeout]) => new Promise((res, rej) => {
             const read = new Function('return (' + expr + ')');
             const t0 = performance.now();
             let last = null, same = 0;
             const tick = () => {
               const v = JSON.stringify(read());
               if (v === last) { if (++same > 3) return res(JSON.parse(v)); }
               else { same = 0; last = v; }
               if (performance.now() - t0 > timeout)
                 return rej(new Error('still moving after ' + timeout + 'ms'));
               requestAnimationFrame(tick);
             };
             requestAnimationFrame(tick);
           })""", [expr, timeout])


def available():
    """Whether there is a Chromium to be had, without skipping on the spot.

    A few of these tests have their own tidying to do before they give up -
    a server thread to stop, a module global to put back - and they cannot do
    it from inside the `with` that never opened.
    """
    try:
        browser()
        return True
    except Exception:
        return False


@contextlib.contextmanager
def session():
    """A browser for one test, with its pages cleaned up after it.

    Anything opened inside the block is closed at the end of it, so nothing a
    test leaves behind can reach the next one. The browser itself stays up.
    """
    br = browser()
    before = list(br.contexts)
    try:
        yield br
    finally:
        for c in list(br.contexts):
            if c not in before:
                try:
                    c.close()
                except Exception:
                    pass


def shutdown():
    """Closed at the end of the run, and again by atexit if pytest dies."""
    global _PW, _BR
    br, pw, _BR, _PW = _BR, _PW, None, None
    for x in (br, pw):
        if x is not None:
            try:
                x.close() if x is br else x.stop()
            except Exception:
                pass


atexit.register(shutdown)
