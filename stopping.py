"""Stop means stop, not "stop after this page".

lee: *"can you make stopping a proccess happen fast it shoud cancel teh page
it woirkingg on and stop not keep finishing it"*.

The Stop button set `job["cancel"]`, and the only place that flag was ever
read was **between pages** -- `_run_one`'s loop checked it, called `fn(i)`, and
then checked it again. So pressing Stop during a clean meant waiting out a
whole page of inpainting, which on a textured page is the slowest thing the
app does. The button was honest about being pressed and dishonest about when
anything would happen.

## HOW THIS WORKS

One flag, read from anywhere, raised as an exception at the next safe moment:

    `watch(fn)`   `_run_one` hands over a predicate that reads `job["cancel"]`
    `check()`     any loop calls it; it raises `Stopped` if Stop was pressed
    `asked()`     the same question without the exception, for code that would
                  rather return early than unwind
    `clear()`     the run is over, and nothing may raise afterwards

A module global rather than a parameter threaded through nine call sites,
because every one of those signatures belongs to something that has nothing
to do with cancelling, and a `should_stop=None` argument on `ocr_page`,
`inpaint_page`, `typeset_page` and everything they call is how a codebase
stops being readable. It is set and cleared in ONE place -- `_run_one`'s
`try/finally` -- so there is no state to leak between runs.

## WHERE IT IS CHECKED, AND WHY THOSE PLACES

At the top of each per-REGION loop, and nowhere finer. A region is the unit
of work a person can see: a balloon read, a balloon cleaned, a balloon
typeset. Checking inside a convolution would be faster to stop and would leave
a page in a state nothing could describe.

## WHAT A STOPPED PAGE IS

Partly done, and honestly so. The pages that finished are saved; the one that
was interrupted keeps whatever it had -- the balloons already read stay read,
the ones not reached stay empty. It is not rolled back, because a rollback
that half-works is worse than a page somebody can simply run again, and
because the alternative is holding a page's worth of edits in memory to undo
them, which is exactly the shape of bug that lost lee's proofreading before.
"""

_asked = None


class Stopped(Exception):
    """Raised at a checkpoint because Stop was pressed.

    Caught by `editor._run_one`, which treats it as a cancelled run rather
    than as an error: nothing went wrong, somebody changed their mind.
    """


def watch(fn) -> None:
    """Hand over the predicate that says whether Stop has been pressed."""
    global _asked
    _asked = fn


def clear() -> None:
    """The run is over. Nothing may raise `Stopped` until the next `watch`."""
    global _asked
    _asked = None


def asked() -> bool:
    """Has Stop been pressed? Never raises, never explodes.

    A predicate that threw would turn "the user clicked Stop" into a crash
    report, so a broken watcher reads as "no".
    """
    fn = _asked
    if fn is None:
        return False
    try:
        return bool(fn())
    except Exception:
        return False


def check() -> None:
    """Raise `Stopped` if Stop has been pressed. The checkpoint."""
    if asked():
        raise Stopped("stopped")
