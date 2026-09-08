"""A page that takes too long says where the time went.

lee timed three of the four cards on his own machine:

    route                 lee     measured here (2 cores, 23 manga pages)
    comic-text-detector    50s     4.7s
    DB++ / COO             58s     9.9s
    Manga109 YOLO26        60s    12.7s

**That is not a multiplier.** Ten times, six times, five times - but subtract
instead of divide and it is 45, 48, 47. The SAME 47 seconds on top of every
route. A cost that does not care which detector ran is not inside any of them:
it belongs to something all three share, and the obvious candidate is getting
the page off the disk before any of them start.

Which is why the load is timed apart from the detecting. Fold it in and it
hides behind whichever route is being blamed:

    find text  003.png  960x1399  DB++ / COO  load  47.2s  detect  9.9s ...
    find text  003.png  960x1399  net 3.1s  craft 4.8s  rest 1.2s ...

Three things make that actionable where "58 seconds" is not.

**The load**, separate, so a fast route behind a slow read says so.

**The page size.** Detection scales with AREA. The same page at 1x is 4.7s
here and at 3x is 21.8s on the same two cores - so a big scan taking a minute
is arithmetic rather than a fault, and the fix is a resize rather than a hunt.

**The split inside comic-text-detector.** CRAFT is started at the top of the
run and collected in the middle, so what it costs is the WAIT the block head
could not hide. If the wait is the whole page, the sound-effect second opinion
is the thing to turn off; if the net is, it is the machine.

And it only speaks when a page was slow. A run that is behaving should not
narrate, or the one line that matters is buried in three hundred that do not.
"""
import time

import pytest

from where import PKG


def test_the_quiet_run_stays_quiet(capsys):
    """Nothing is said about a page that came back in the time it should."""
    from mangatl.detect import comictext as CT

    class _P:
        image = None
        source_path = "004.png"

    CT._say_timing(_P(), 0.0, 0.1, 0.2, 7, True)     # t0=0 -> "took" is huge
    said = capsys.readouterr().err
    assert said, "a page timed from the epoch is slow by any measure"

    import time as _t
    now = _t.time()
    CT._say_timing(_P(), now, now, now, 7, True)
    assert not capsys.readouterr().err, "a page that took no time says nothing"


def test_the_threshold_is_under_what_lee_timed_and_over_what_it_costs():
    """2.94 to 14.3 s a page is every route behaving. 50 is what he saw."""
    from mangatl.detect import comictext as CT
    from mangatl import project as P

    assert 14.3 < CT.SAY_OVER < 50
    assert 14.3 < P.SAY_PAGE_OVER < 50


def test_the_line_carries_the_page_size(capsys):
    """Half the answer. Without it a slow page and a huge page look alike."""
    import numpy as np
    from mangatl.detect import comictext as CT

    class _P:
        image = np.zeros((1399, 960, 3), np.uint8)
        source_path = "/somewhere/003.png"

    CT._say_timing(_P(), 0.0, 0.1, 0.2, 11, True)
    said = capsys.readouterr().err
    assert "960x1399" in said
    assert "003.png" in said and "/somewhere/" not in said, "the name, not the path"
    assert "net" in said and "craft" in said and "rest" in said


def test_the_split_adds_up_to_the_total(capsys):
    """Three numbers that do not sum to the fourth are three lies."""
    import re
    from mangatl.detect import comictext as CT

    class _P:
        image = None
        source_path = "005.png"

    CT._say_timing(_P(), 0.0, 10.0, 30.0, 3, True)
    said = capsys.readouterr().err
    net, craft, rest, total = (float(x) for x in
                               re.findall(r"(\d+\.\d)s", said))
    assert net == 10.0 and craft == 20.0
    assert abs((net + craft + rest) - total) < 0.2


def _proj(**s):
    """A Project with no folder: `_say_page_cost` reads settings and nothing
    else off it, and building a real one wants a directory of pages."""
    from mangatl.project import Project

    class _Proj(Project):
        def __init__(self, **st):
            self.settings = dict(st)
            self.settings.setdefault("medium", "manga")

        def _picked(self, key):
            return bool(self.settings.get(key)) and self.route_here(key)

        def two_specialists(self):
            return self._picked("two_specialists")

        def manga_segmenter(self):
            return self._picked("manga_segmenter")

        def animetext(self):
            return self._picked("animetext")

        def webtoon_ko(self):
            return self._picked("webtoon_ko")

        def webtoon_zh(self):
            return self._picked("webtoon_zh")

    return _Proj(**s)


def test_the_page_line_names_which_route_spent_it(capsys):
    """Four cards, and a total that does not say which one was picked is a
    total nobody can act on. The card names are the ones on screen."""
    from mangatl.project import _say_page_cost

    class _P:
        image = None
        source_path = "006.png"

    # The name has to be the route that RAN, so `route_name` asks each route's
    # own predicate - which asks whether the checkpoint is on this machine.
    # That is not what this test is about, so the predicates are the flag and
    # the format guard and nothing else. Borrowing `route_name` alone stopped
    # working the day it started asking, which is the point of a stub this
    # thin: it fails loudly rather than answering something plausible.
    for key, name in (("two_specialists", "DB++ / COO"),
                      ("animetext", "AnimeText YOLO12-L"),
                      ("manga_segmenter", "Manga109 YOLO26"),
                      ("webtoon_ko", "Webtoon balloons KO"),
                      ("webtoon_zh", "Webtoon balloons ZH")):
        p = _proj(**{key: True,
                     "medium": "manhwa" if key.startswith("webtoon") else
                               "manga"})
        _say_page_cost(p, _P(), 0.0, 5)
        assert name in capsys.readouterr().err, key
    _say_page_cost(_proj(), _P(), 0.0, 5)
    assert "comic-text-detector" in capsys.readouterr().err


def test_the_first_page_of_a_run_always_says_so(capsys):
    """lee: *"koren detector is taking 13 second per page"*.

    Thirteen is under the bar, so a whole chapter ran and left nothing on
    record at all - not the route, not the page size, not the machine line,
    which is the one fact that turns "slow" into a diagnosis. The bar exists
    so a run that behaves stays quiet, and one line at the top of a run is
    not noise: it is the baseline every later line is read against, and on a
    run where nothing is slow enough to complain it is the only line there
    is."""
    from mangatl.project import _say_page_cost

    class _P:
        image = None
        source_path = "001.png"

    _say_page_cost._machine_said = False
    _say_page_cost(_proj(), _P(), time.time(), 5)
    said = capsys.readouterr().err
    assert "machine" in said, "and the machine line above it"
    assert "find text  001.png" in said, said
    # ...and the second is silent again, because it was quick.
    _say_page_cost(_proj(), _P(), time.time(), 5)
    assert not capsys.readouterr().err


def test_the_webtoon_route_says_where_inside_itself_it_went(capsys):
    """"Thirteen seconds" cannot be acted on. This route is two models with
    completely different shapes of cost - comic-text-detector's segmentation,
    one fixed pass that does not care how tall the page is, and one small
    pass per tile that does - so which of them the time is in is the whole
    question, and neither a total nor a page size answers it."""
    from mangatl.detect import webtoon as WT
    from mangatl.project import _say_page_cost

    class _P:
        image = None
        source_path = "001.png"

    WT.LAST_SPLIT = "mask 11.4s  boxes 1.2s  ink 0.1s  5 tiles"
    _say_page_cost._machine_said = False
    _say_page_cost(_proj(medium="manhwa", webtoon_ko=True), _P(),
                   time.time(), 5)
    said = capsys.readouterr().err
    assert "mask 11.4s" in said and "5 tiles" in said, said
    # ...and a route that does not report one says nothing extra.
    _say_page_cost._machine_said = False
    _say_page_cost(_proj(medium="manga", animetext=True), _P(),
                   time.time(), 5)
    assert "mask 11.4s" not in capsys.readouterr().err


def test_a_route_the_format_does_not_offer_is_not_the_name(capsys):
    """`webtoon_ko` ships ON so a strip gets a webtoon default with no
    per-format defaults table, which means on a MANGA the flag is set and the
    route is guarded off. A line naming a route that never ran is worse than
    no line."""
    from mangatl.project import _say_page_cost

    class _P:
        image = None
        source_path = "006.png"

    _say_page_cost(_proj(medium="manga", webtoon_ko=True, animetext=True),
                   _P(), 0.0, 5)
    said = capsys.readouterr().err
    assert "AnimeText" in said and "Webtoon" not in said


def test_getting_the_page_off_the_disk_is_its_own_number(capsys):
    """The whole reason this exists. lee's four routes came in at 50, 58 and
    60 seconds against 4.7, 9.9 and 12.7 measured here - the same 47 seconds
    on top of each, not a factor. A constant that does not care which detector
    ran is not in any detector, so the load cannot be folded into their time
    or it hides behind whichever route is being blamed this week."""
    import time as _t
    from mangatl.project import _say_page_cost

    _Proj = _proj

    class _P:
        image = None
        source_path = "007.png"

    now = _t.time()
    _say_page_cost(_Proj(), _P(), now, 5, load=47.0)
    said = capsys.readouterr().err
    assert "load  47.0s" in said, said
    assert "detect    0.0s" in said, "a fast route behind a slow load says so"
    # ...and a page that was quick on both is still silent.
    _say_page_cost(_Proj(), _P(), _t.time(), 5, load=0.1)
    assert not capsys.readouterr().err


def test_the_line_also_lands_in_a_file_in_the_project_folder(tmp_path):
    """The console is the one place lee never looks - the app is started by a
    double-click on Windows and the window behind it might as well not exist.
    `out/slow-pages.txt` can be read after the run, sent, or looked at over
    the bridge. Appended, because the pattern ACROSS a run is the diagnosis:
    one slow page is a load, every page slow is the machine."""
    from mangatl.project import _say_page_cost

    def _Proj():
        p = _proj()
        p.output_dir = str(tmp_path)
        return p

    class _P:
        image = None
        source_path = "008.png"

    _say_page_cost(_Proj(), _P(), 0.0, 4, load=30.0)
    _say_page_cost(_Proj(), _P(), 0.0, 4, load=30.0)
    got = (tmp_path / "slow-pages.txt").read_text(encoding="utf-8")
    assert got.count("008.png") == 2, "appended, not overwritten"
    assert "load  30.0s" in got
    # ...and a quick page adds nothing.
    import time as _t
    _say_page_cost(_Proj(), _P(), _t.time(), 4, load=0.0)
    assert (tmp_path / "slow-pages.txt").read_text(
        encoding="utf-8").count("008.png") == 2


def test_the_first_slow_page_carries_a_line_about_the_machine(tmp_path):
    """lee's comic-text-detector forward was 65-72s against 2.5 here - 27x on
    ONE runtime while his torch models ran at ordinary speed. Profiled, that
    is the mask decoder's ConvTranspose stack, which OpenCV runs through its
    own GEMM: fast under AVX2, grim without it. Whether the CPU HAS AVX2 is
    the whole diagnosis, and no amount of timing pages surfaces it - so the
    first slow page of a process writes down what the machine is."""
    from mangatl.project import Project, _machine_line, _say_page_cost

    said = _machine_line()
    assert said.startswith("machine")
    assert "opencv" in said and "cores" in said and "gemm" in said

    def _Proj():
        p = _proj()
        p.output_dir = str(tmp_path)
        return p

    class _P:
        image = None
        source_path = "009.png"

    _say_page_cost._machine_said = False
    _say_page_cost(_Proj(), _P(), 0.0, 4, load=30.0)
    _say_page_cost(_Proj(), _P(), 0.0, 4, load=30.0)
    got = (tmp_path / "slow-pages.txt").read_text(encoding="utf-8")
    assert got.count("machine") == 1, "once per process, not once per page"
    assert got.index("machine") < got.index("009.png"), "above the first page"


def test_the_threads_are_reclaimed_every_time_the_net_is_fetched():
    """lee's machine line: `opencv 5.0.0  threads 1  cores 20`. One thread of
    twenty, 65 seconds a page, and nothing in this codebase set it to 1 - some
    import did. So it is reclaimed on EVERY `_get_net`, not once at startup:
    whoever knocked it down can knock it down again, and the page after they
    do must not cost a minute."""
    import os
    import cv2
    from mangatl.detect import comictext as CT

    before = cv2.getNumThreads()
    try:
        cv2.setNumThreads(1)
        CT._all_the_cores()
        assert cv2.getNumThreads() == (os.cpu_count() or 1)
    finally:
        cv2.setNumThreads(before)
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    body = src[src.index("def _get_net("):src.index("def _letterbox(")]
    assert "_all_the_cores()" in body, "reclaimed where every route fetches"


def test_opencv_five_is_kept_out_and_named_when_present(monkeypatch):
    """5.0's new dnn engine runs the detector 2.4x slower than 4.11 -
    measured, same page, same machine: 5.7s against 2.5s. The pin keeps new
    installs on what the cards were measured on, and the machine line carries
    the one command that fixes an install already on 5."""
    req = (PKG / "requirements.txt").read_text(encoding="utf-8")
    assert "opencv-contrib-python-headless>=4.8,<5" in req

    import cv2
    from mangatl.project import _machine_line
    monkeypatch.setattr(cv2, "__version__", "5.0.0")
    said = _machine_line()
    assert "pip install" in said and "<5" in said
    monkeypatch.setattr(cv2, "__version__", "4.11.0")
    assert "pip install" not in _machine_line()


def test_it_is_measured_round_the_route_and_not_round_the_whole_step():
    """`detect` also crops, labels, drops and orders. Timing all of that would
    blame the detector for work it did not do."""
    src = (PKG / "project.py").read_text(encoding="utf-8")
    at = src.index("found = self._detect_measured(page, kinds, detector, weights)")
    assert "_t0 = time.time()" in src[at - 800:at]
    assert "_say_page_cost(self, page, _t0" in src[at:at + 200]


def test_the_wait_on_craft_is_what_is_reported_not_its_runtime():
    """It is started at the top and collected in the middle, on purpose - the
    block head hides most of it. Reporting its runtime would say the page cost
    time it never spent."""
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    start = src.index("craft_job = _POOL.submit(_craft.pieces, img, **knobs)")
    mark = src.index("_t_net = _time.time()")
    join = src.index("craft_pieces = craft_job.result()")
    assert start < mark < join, "the clock stops before the wait, not after it"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
