"""The 93% of Find text, and the only thing that made it cheaper for free.

lee: *"i relly wan to decrease teh time it takes because riht now it takes
froever"*.

Timed end to end through `Project.detect` over his 32-page chapter, with the
two nets clocked separately::

    8 pages: 79.0s  (9.87s a page)
      detect_comictext         78.7s   100%
      craft.pieces             73.3s    93%

CRAFT is the whole cost. The block head is 2.2 seconds and starts at the same
moment CRAFT does, so it finishes inside CRAFT's window and costs nothing; the
measuring this package does for itself -- the harvest, the walls, the grow, the
kinds, the balloons, the ordering, the commit -- is 5.4 seconds spread over all
32 pages.

So every idea that speeds up anything else is worth nothing, and the ideas that
speed up CRAFT split in two.

**Give it less to look at.** Its canvas at 1600 is nearly twice as fast and
changes what is found on seven of twelve pages, every change a box lost: 014
from 3 to 2, 022 from 4 to 3, 029 from 8 to 6. At 2048 it still moves three of
twelve. lee's rule has never changed -- a missed sound effect is worse than a
slow one -- so the resolution is not on the table and this file's first test
says so.

**Do the same arithmetic better.** Four runtimes were measured on page 029,
against the eager baseline of 7.45s::

    channels_last              5.76s   maxdiff 1.1e-06   free
    + batch-norm folding       5.32s   maxdiff 1.3e-06   30s of tracing
    torch.compile              4.79s   maxdiff 1.4e-06   65s, and a C++ compiler
    onnxruntime               70.93s                     32x SLOWER, not a typo
    bfloat16                  17.63s   maxdiff 2.0e-02   no bf16 on this CPU

Only the first is free, and free is what ships: lee clicks Find text on single
pages as often as on chapters, and a startup cost he pays every session is not
a speed-up. `torch.compile` wants MSVC on Windows, which is what he is on.

The whole chapter, found twice and compared region by region -- rectangle, kind
and reading order::

    as it ships   : 32 pages in 332.1s (10.38s a page)
    channels_last : 32 pages in 278.6s ( 8.71s a page)
    pages whose boxes differ: 0

That is the shape of the claim these tests guard: the layout is asked for, it
is asked for ONCE, and asking for it can never be what breaks Find text.
"""
import pytest

from where import PKG

from mangatl.detect import craft as CR


# ------------------------------------------------- the resolution stays put

def test_the_canvas_is_still_the_measured_one():
    """The cheap 2x, and why it is not taken.

    Lowering `CANVAS` is the biggest saving available anywhere in Find text and
    it pays for itself in lost boxes. Page 029 comes back with 6 of its 8. If
    this number ever moves, the sweep has to be done again on a chapter and the
    losses counted, because the last person to sweep it found losses.
    """
    assert CR.CANVAS == 2560
    assert CR.MAG_RATIO == 1.0


# ------------------------------------------------- the layout is asked for

class _Det:
    def __init__(self):
        self.asked = []

    def to(self, **kw):
        self.asked.append(kw)
        return self


class _Reader:
    def __init__(self):
        self.detector = _Det()


def test_the_weights_are_laid_out_for_the_cpu():
    """channels_last, and nothing else."""
    import torch
    r = _Reader()
    CR.lay_out_for_the_cpu(r)
    assert r.detector.asked == [{"memory_format": torch.channels_last}]


def test_it_is_asked_for_once_when_the_reader_is_built(monkeypatch):
    """Per reader, not per page.

    The layout belongs to the weights. Turning them over on every call would
    copy 20 million floats a page to arrive at the arrangement they were
    already in.
    """
    made = []
    laid = []

    class FakeReader:
        def __init__(self, langs, gpu=False, verbose=False):
            made.append(tuple(langs))
            self.detector = _Det()

    import sys
    import types
    fake = types.ModuleType("easyocr")
    fake.Reader = FakeReader
    monkeypatch.setitem(sys.modules, "easyocr", fake)
    monkeypatch.setattr(CR, "_readers", {})
    monkeypatch.setattr(CR, "lay_out_for_the_cpu",
                        lambda r: laid.append(r))

    a = CR._reader(("ko", "en"))
    b = CR._reader(("ko", "en"))
    assert a is b                      # the reader is cached, as it always was
    assert made == [("ko", "en")]      # built once
    assert laid == [a]                 # and laid out once, with it


def test_the_reader_is_still_one_per_language_set(monkeypatch):
    """A second language set gets its own reader and its own layout."""
    laid = []

    class FakeReader:
        def __init__(self, langs, gpu=False, verbose=False):
            self.detector = _Det()

    import sys
    import types
    fake = types.ModuleType("easyocr")
    fake.Reader = FakeReader
    monkeypatch.setitem(sys.modules, "easyocr", fake)
    monkeypatch.setattr(CR, "_readers", {})
    monkeypatch.setattr(CR, "lay_out_for_the_cpu", lambda r: laid.append(r))

    a = CR._reader(("ko", "en"))
    b = CR._reader(("ja", "en"))
    assert a is not b
    assert laid == [a, b]


# ------------------------------------------------- and it can never break it

def test_a_torch_that_refuses_leaves_find_text_alone():
    """A slower Find text, not a traceback.

    This is a speed-up and only a speed-up. A torch too old for the flag, or an
    easyocr that stops calling its detector `detector`, must cost a second a
    page and nothing else.
    """
    class Angry:
        def to(self, **kw):
            raise RuntimeError("no such memory format")

    class R:
        detector = Angry()

    CR.lay_out_for_the_cpu(R())        # must not raise


def test_a_reader_with_no_detector_at_all_is_survivable():
    class R:
        pass

    CR.lay_out_for_the_cpu(R())        # must not raise


def test_the_reader_is_still_built_when_the_layout_blows_up(monkeypatch):
    """The reader is what the caller asked for. If laying it out fails the
    caller still gets a working reader -- and gets it CACHED, so a machine
    where the flag is unavailable does not rebuild the weights every page."""
    class FakeReader:
        def __init__(self, langs, gpu=False, verbose=False):
            self.detector = _Det()

    import sys
    import types
    fake = types.ModuleType("easyocr")
    fake.Reader = FakeReader
    monkeypatch.setitem(sys.modules, "easyocr", fake)
    monkeypatch.setattr(CR, "_readers", {})

    a = CR._reader(("ko", "en"))       # real lay_out_for_the_cpu, fake torch call
    b = CR._reader(("ko", "en"))
    assert a is b


def test_the_module_still_reports_whether_craft_can_run():
    """`available()` is what stands between a machine with no easyocr and a
    traceback, and none of this touched it."""
    assert CR.available() in (True, False)


def test_the_helper_is_public_enough_to_be_found():
    """No leading underscore. It is the answer to `where did the 16% go`, and
    the next person to profile Find text should be able to grep for it."""
    assert hasattr(CR, "lay_out_for_the_cpu")
    assert not CR.lay_out_for_the_cpu.__name__.startswith("_")
    assert "93%" in (CR.lay_out_for_the_cpu.__doc__ or "")


def test_the_file_still_reads_as_the_second_pair_of_eyes():
    src = (PKG / "detect" / "craft.py").read_text(encoding="utf-8")
    assert "channels_last" in src
    # The saving is recorded where the change is, with the number that was
    # measured, so nobody has to re-derive it to know whether it is worth it.
    assert "10.38" in src and "8.71" in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
