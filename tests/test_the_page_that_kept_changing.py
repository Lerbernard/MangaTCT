"""The page that cleaned itself over and over, and was billed for each go.

lee, with two screenshots of the same page: *"when i firt didi te clean it didi
not look like thsi after a while it turn into this what happened"*.

Nothing about his project had changed. The page was being cleaned again and
again, and each attempt came back different.

## The chain

A plate built while the hosted cleaner refused a box is deliberately NOT
cached - so that pressing Clean again really retries instead of finding the
smeared plate on disk. `cleaned` was set all the same, and `_worth_warming`
read `cleaned` as "already paid for, cached on disk". The background
page-builder therefore walked past that page every time the render cache
turned over (96 entries, and a 23-page chapter fills that), rebuilt it from
scratch, and called the endpoint again. A flaky endpoint refuses a DIFFERENT
subset of boxes each time, so a different mix of the model's work and the
local fallback landed on the page - and the per-page fee was charged on every
one of those silent rebuilds. Measured before the fix: three visits to one
page, three fees, 39,407 and then 56,210 pixels of difference between them.

## What it is now

lee: *"make it so that teh failed build dont get show and teh ai attemsp shoud
happen in teh timmer not in the background and it shoud deliver the proper
clen page even if it takes longer"*, and then: *"add a setting in teh clenner
that will allw the editor to charge for failed builds , and if its off then
teh first build shoud get shown even if it failes"*.

* **Warming reads the file, not the flag.** `cleaned` is a claim that Clean was
  pressed; the plate on disk is the fact that its answer was kept.
* **The retries happen in `do_clean`**, where the progress bar is, and they are
  cheap: `_ai_clean_call` caches every answer the endpoint did give by the
  content of its own (image, mask), so a second go only asks about the boxes
  that failed. One press of Clean carries one page fee however many goes it
  takes.
* **A refused build is thrown away, not shown, and not billed.** The fee is
  for a page you got; a build nobody kept is not one, however many times it is
  attempted. lee: *"ill just eat the extra cost , can you fx this thought ...
  1 more every time you open that page"*.
* **Only the button goes to the model.** `render_index` has said "looking at a
  page is not cleaning it" for a long time, but Typeset and Export call
  `clean_page` directly, so on a page with no plate they rebuilt it and went
  back to the endpoint. With the hosted cleaner on, a page nobody has cleaned
  is simply not cleaned and everything downstream gets the scan. lee: *"it
  shoudnt rebuild everytime, it shoud ony go to the ai when i clcik the
  button, and save the good result on the cash eor soemthing"* - and the good
  result IS saved: every answer the endpoint gives is cached inside
  `_ai_clean_call` by its own (image, mask), so a later press only asks about
  the boxes that failed.
"""
import shutil

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")

from mangatl import editor as E
from mangatl.project import Project


def _project(root, hosted=True):
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    # Hatching, so the boxes are not plain white bubbles: a flat bubble is
    # filled locally and never reaches the endpoint, and this is a test about
    # what the endpoint does.
    img = np.full((300, 420, 3), 250, np.uint8)
    img[:, ::4] = 70
    for k, x in enumerate((30, 170, 300)):
        cv2.putText(img, "!!", (x, 120 + 60 * (k % 2)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.6, (15, 15, 15), 7)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [
        {"id": k + 1, "kind": "sfx", "order": k,
         "bbox": [x - 6, 78 + 60 * (k % 2), 92, 56], "bubble_bbox": None,
         "src_text": "テスト", "dst_text": "TEST", "confidence": 0.9}
        for k, x in enumerate((30, 170, 300))]
    p.pages[0].detected = True
    p.settings["ai_clean"] = "all" if hosted else "off"
    p.settings["clean_url"] = "https://example.invalid/clean" if hosted else ""
    return p


class _Endpoint:
    """A hosted cleaner that refuses some of what it is asked.

    `first` refuses that many calls before ever answering - one whole build's
    worth is what a page that comes good on the second go looks like. `every`
    refuses one call in that many for ever, which is the flaky endpoint that
    started all this: some boxes answered, some not, a different set each go.
    """

    def __init__(self, first=0, every=0):
        self.first, self.every, self.calls = first, every, 0

    def __call__(self, p, strict=False, brush=False):
        def neural(img, mask):
            self.calls += 1
            bad = (self.calls <= self.first
                   or (self.every and self.calls % self.every == 0))
            if bad:
                E._AI_CLEAN_FAIL["n"] += 1
                E._AI_CLEAN_FAIL["msg"] = "refused (test)"
                return None
            out = img.copy()
            src = np.roll(img, 24, axis=0)
            m = mask > 0
            out[m] = src[m]
            return out
        return neural, True


def _run(root, first=0, every=0, hosted=True, tries=2):
    """Press Clean once, then open the page twice more. Returns the bill."""
    from mangatl import coins
    charges = []
    p = _project(root, hosted)
    old = (E._make_cleaner, E._make_reader, E.CLEAN_TRIES, E.CLEAN_WAIT,
           coins.flat)
    E._make_cleaner = _Endpoint(first, every)
    E._make_reader = lambda p_: None
    E.CLEAN_TRIES, E.CLEAN_WAIT = tries, 0.0
    coins.flat = lambda c, what="", page="": charges.append((c, what)) or 0
    E._AI_CLEAN_FAIL.update(n=0, msg="", refused="")
    plates = []
    try:
        E.do_clean(p, 0, force=True)
        pressed = len(charges)
        asked = E._make_cleaner.calls
        for _ in range(2):
            E._plate_cache.clear()
            page = p.materialize(0)
            E.clean_page(p, 0, page)          # ...as Typeset and Export do
            plates.append(page.clean_plate.copy())
        return dict(p=p, pressed=pressed, total=len(charges), plates=plates,
                    asked=asked, asked_after=E._make_cleaner.calls - asked,
                    on_disk=__import__("os").path.exists(
                        E._plate_disk_path(p, 0)),
                    shown=bool(p.pages[0].cleaned))
    finally:
        (E._make_cleaner, E._make_reader, E.CLEAN_TRIES, E.CLEAN_WAIT,
         coins.flat) = old
        E._AI_CLEAN_FAIL.update(n=0, msg="", refused="")
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------- 1. the background stops cleaning

def test_warming_leaves_alone_a_page_whose_plate_is_not_on_disk():
    """The regression, stated as the rule it broke: `cleaned` is a claim and
    the file is the fact, and warming may only spend on the fact."""
    root = scratch("_tmp_warm_flag")
    p = _project(root, hosted=True)
    try:
        p.pages[0].cleaned = True                  # Clean was pressed...
        assert not __import__("os").path.exists(E._plate_disk_path(p, 0))
        assert not E._worth_warming(p, 0), \
            "the page-builder would clean this page again, in the background"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_warming_builds_a_page_whose_plate_is_on_disk():
    root = scratch("_tmp_warm_disk")
    p = _project(root, hosted=True)
    try:
        fp = E._plate_disk_path(p, 0)
        __import__("os").makedirs(__import__("os").path.dirname(fp),
                                  exist_ok=True)
        cv2.imwrite(fp, p.materialize(0).image)
        assert E._worth_warming(p, 0), "already paid for: rebuild it freely"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_local_cleaning_is_still_warmed_whatever_the_flag_says():
    """Warming is a kindness while it stays on this machine, and it stays a
    kindness - the rule above is about spending the hosted cleaner."""
    root = scratch("_tmp_warm_local")
    p = _project(root, hosted=False)
    try:
        assert E._worth_warming(p, 0)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------- 2. what a refused build is worth

def test_the_best_of_the_failed_goes_is_what_the_page_keeps():
    """A page with most of its Japanese off is worth more than a page with
    none of it off, and pressing Clean again is how another try is asked for.
    lee: *"if teh build failes after 4 trues still show teh nbest version fo
    teh failes so we show shoeming"*."""
    got = _run(scratch("_tmp_best"), every=3, tries=3)
    assert got["on_disk"], "nothing was kept, so the page shows the bare scan"
    assert got["shown"], "the page reads as not cleaned, so nothing is drawn"


def test_and_best_means_the_go_the_model_did_most_of():
    """Not the last go, and not the first: the one the endpoint refused fewest
    boxes on."""
    from mangatl import coins
    root = scratch("_tmp_bestof")
    p = _project(root)

    class _Fading:
        """Refuses three boxes, then one, then two - so the best is the middle
        go and neither end of the run."""

        def __init__(self):
            self.go, self.n = -1, 0

        def __call__(self, p_, strict=False, brush=False):
            self.go += 1
            self.n = 0
            refuse = (3, 1, 2)[min(self.go, 2)]

            def neural(img, mask):
                self.n += 1
                if self.n <= refuse:
                    E._AI_CLEAN_FAIL["n"] += 1
                    return None
                out = img.copy()
                m = mask > 0
                out[m] = np.roll(img, 24, axis=0)[m]
                return out
            return neural, True

    seen, kept = [], []
    _fin, _store = E._finish_plate, E._store_plate
    old = (E._make_cleaner, E._make_reader, E.CLEAN_TRIES, E.CLEAN_WAIT,
           coins.flat)
    E._make_cleaner = _Fading()
    E._make_reader = lambda p_: None
    E.CLEAN_TRIES, E.CLEAN_WAIT = 3, 0.0
    coins.flat = lambda c, what="", page="": 0
    E._finish_plate = lambda p_, i_, pg, full, inc: (
        seen.append(full.copy()), _fin(p_, i_, pg, full, inc))[1]
    E._store_plate = lambda p_, i_, full: (kept.append(full.copy()),
                                           _store(p_, i_, full))[1]
    E.clear_clean_warning()
    try:
        E.do_clean(p, 0, force=True)
        assert len(seen) == 3, "the fixture did not make three goes: %d" % len(seen)
        assert len(kept) == 1, kept
        same = [k for k, g in enumerate(seen)
                if np.array_equal(g, kept[0])]
        assert same == [1], ("kept go %s, and the best one was go 1" % same)
    finally:
        (E._make_cleaner, E._make_reader, E.CLEAN_TRIES, E.CLEAN_WAIT,
         coins.flat) = old
        E._finish_plate, E._store_plate = _fin, _store
        E.clear_clean_warning()
        shutil.rmtree(root, ignore_errors=True)


def test_and_it_is_not_billed_however_many_times_it_is_attempted():
    """The fee is for a page you got. lee, on being charged again every time
    he opened one: *"ill just eat the extra cost , can you fx this thought"*."""
    got = _run(scratch("_tmp_keep"), every=3, tries=3)
    assert got["total"] == 0, ("a build nobody kept was billed", got["total"])


def test_opening_the_page_afterwards_does_not_go_back_to_the_model():
    """Typeset and Export call `clean_page` directly, so a page with no plate
    used to be rebuilt - and re-asked - by each of them. lee: *"it shoudnt
    rebuild everytime, it shoud ony go to the ai when i clcik the button"*."""
    got = _run(scratch("_tmp_again"), every=3)
    assert got["asked"] > 0, "the fixture never reached the endpoint at all"
    assert got["asked_after"] == 0, \
        "opening the page called the cleaner %d more times" % got["asked_after"]
    assert got["total"] == got["pressed"], \
        "opening the page was billed as well as pressing Clean"


def test_a_page_with_nothing_to_keep_shows_the_scan():
    """One go, refused outright, nothing worth keeping - and then it is the
    page as it came in rather than a blank or a smear."""
    root = scratch("_tmp_scan")
    p = _project(root)
    from mangatl import coins
    old = (E._make_cleaner, E._make_reader, E.CLEAN_TRIES, E.CLEAN_WAIT,
           coins.flat)
    E._make_cleaner = _Endpoint(every=1)
    E._make_reader = lambda p_: None
    E.CLEAN_TRIES, E.CLEAN_WAIT = 1, 0.0
    coins.flat = lambda c, what="", page="": 0
    E.clear_clean_warning()
    try:
        E._KEEP_BEST.update(on=False, fails=None, plate=None)
        with_nothing = E._KEEP_BEST["plate"]
        assert with_nothing is None
        E.do_clean(p, 0, force=True)
        # every box refused: the "best" go still cleaned nothing by the model,
        # and what is kept is the local fill, which is a page - so what must
        # never happen is a BLANK.
        E._plate_cache.clear()
        page = p.materialize(0)
        E.clean_page(p, 0, page)
        assert page.clean_plate is not None
        assert page.clean_plate.shape == page.image.shape
    finally:
        (E._make_cleaner, E._make_reader, E.CLEAN_TRIES, E.CLEAN_WAIT,
         coins.flat) = old
        E.clear_clean_warning()
        shutil.rmtree(root, ignore_errors=True)


def test_the_local_cleaner_is_never_held_back_like_that():
    """It is somebody's own CPU: free, fast, and refusing it would leave a
    page uncleaned for no reason at all."""
    root = scratch("_tmp_local_build")
    p = _project(root, hosted=False)
    try:
        page = p.materialize(0)
        E.clean_page(p, 0, page)
        assert not np.array_equal(page.clean_plate, page.image), \
            "a local clean did nothing"
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------- 3. the retry delivers the page

def test_clean_goes_back_at_a_page_the_endpoint_refused_once():
    """*"it shoud deliver the proper clen page even if it takes longer"*."""
    got = _run(scratch("_tmp_retry"), first=3, tries=4)
    assert got["shown"], "the page never came out whole"
    assert got["on_disk"]
    assert got["total"] == 1, ("a page that came out whole is one page fee",
                               got["total"])


def _calls_for(root, fatal):
    """How many times the endpoint is asked, over one press of Clean."""
    from mangatl import coins
    p = _project(root)
    ep = _Endpoint(every=1)

    def cleaner(p_, strict=False, brush=False):
        fn, all_ = ep(p_, strict, brush)

        def neural(img, mask):
            if fatal:
                # what a 401 does: `_ai_clean_call` turns back at the top from
                # here on, for this (url, token), for the rest of the run
                E._AI_CLEAN_FAIL["refused"] = "url|token"
            return fn(img, mask)
        return neural, all_

    old = (E._make_cleaner, E._make_reader, E.CLEAN_TRIES, E.CLEAN_WAIT,
           coins.flat)
    E._make_cleaner = cleaner
    E._make_reader = lambda p_: None
    E.CLEAN_TRIES, E.CLEAN_WAIT = 4, 0.0
    coins.flat = lambda c, what="", page="": 0
    E._AI_CLEAN_FAIL.update(n=0, msg="", refused="")
    try:
        E.do_clean(p, 0, force=True)
        return ep.calls
    finally:
        (E._make_cleaner, E._make_reader, E.CLEAN_TRIES, E.CLEAN_WAIT,
         coins.flat) = old
        E._AI_CLEAN_FAIL.update(n=0, msg="", refused="")
        shutil.rmtree(root, ignore_errors=True)


def test_a_refusal_that_waiting_cannot_mend_stops_the_retries():
    """A 401 or a 403 sets `refused`, and every later call turns back at the
    top of `_ai_clean_call` without leaving the machine. Going back four times
    to be told the same thing is four times the wait for the same answer, so
    the loop stops at the first one.

    Counted rather than named, because how many calls ONE build makes is the
    second pass's business and not this test's.
    """
    patient = _calls_for(scratch("_tmp_patient"), fatal=False)
    fatal = _calls_for(scratch("_tmp_fatal"), fatal=True)
    assert patient > fatal, (patient, fatal)
    assert fatal * 3 <= patient, ("it went back at a cleaner that had refused "
                                  "for good: %d calls against %d" % (fatal,
                                                                     patient))


def test_one_page_pays_for_the_waiting_and_the_rest_of_the_run_believes_it():
    """Going back at a page is worth a wait. Going back at every page of a
    chapter because the endpoint is down is that wait times twenty-three, for
    an answer the first page already gave.

    A 401 has `refused` for this and turns back inside `_ai_clean_call`. A dead
    host has nothing of the kind - it is a fresh timeout every time - so the
    run remembers instead.
    """
    from mangatl import coins
    root = scratch("_tmp_giveup")
    p = _project(root)
    ep = _Endpoint(every=1)
    old = (E._make_cleaner, E._make_reader, E.CLEAN_TRIES, E.CLEAN_WAIT,
           coins.flat)
    E._make_cleaner = ep
    E._make_reader = lambda p_: None
    E.CLEAN_TRIES, E.CLEAN_WAIT = 4, 0.0
    coins.flat = lambda c, what="", page="": 0
    E.clear_clean_warning()
    try:
        E.do_clean(p, 0, force=True)
        first = ep.calls
        assert E._CLEAN_GIVEUP["on"], "the run did not notice it had given up"
        E.do_clean(p, 0, force=True)
        second = ep.calls - first
        assert second * 2 <= first, ("the second page waited it out again: "
                                     "%d calls against %d" % (second, first))
        E.clear_clean_warning()
        assert not E._CLEAN_GIVEUP["on"], "it outlived the run that set it"
    finally:
        (E._make_cleaner, E._make_reader, E.CLEAN_TRIES, E.CLEAN_WAIT,
         coins.flat) = old
        E.clear_clean_warning()
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------- 4. and no setting to get wrong

def test_there_is_no_switch_for_any_of_this():
    """It was one for an afternoon, with both answers measured. lee, having
    seen them: *"remove the siwth and just hae it on by default ill just eat
    the extra cost"* - and then the half he actually wanted fixed was the fee,
    which is now nothing at all rather than a choice."""
    from where import PKG
    # ("_pj.py", the old project.py snapshot, went in the 2026-09-02
    # dead-code sweep.)
    for mod in ("project.py", "editor.py"):
        assert "charge_failed" not in (PKG / mod).read_text(encoding="utf-8"), mod
    for f in ("static/editor.html", "static/js/project.js"):
        assert "charge_failed" not in (PKG / f).read_text(encoding="utf-8"), f
