"""Long actions line up instead of trampling each other.

lee: *"add a buttion with a queue fro the loading bar so if somethin gis
happeningfro exmaple cleeening and i click typeseete it shod be added to teh
queue ... allow me to move the iteme sin teh queue and cancek them"*.

Every long action in the app goes through `run_job`, which used to start a
thread there and then. Two at once share one `p.job`, so the bar reported
whichever wrote last and the two runs walked over each other's pages - in
practice you had to sit and wait before pressing anything else.

Now `run_job` puts the work in a line and one dispatcher takes it off, one at a
time, in order. What is RUNNING is not in the line: it is stopped with Cancel,
which has to interrupt a page rather than decline to start.
"""
import shutil
import threading
import time

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import editor
from mangatl.project import Project
from scratch import scratch
from where import PKG


@pytest.fixture
def proj():
    root = scratch("_tmp_queue")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((200, 160, 3), 240, np.uint8)
    for k in range(3):
        p.add_uploaded(f"p{k}.png", cv2.imencode(".png", img)[1].tobytes())
    _quiet()
    yield p
    _quiet()
    # Retire the page warmer as well. It is a background thread reading the
    # pages, and pulling the folder out from under it fills the log with
    # tracebacks from a test that has already passed.
    editor._warm["gen"] += 1
    shutil.rmtree(root, ignore_errors=True)


def _quiet(secs=5.0):
    """Leave the queue empty and no dispatcher running.

    Waiting for the dispatcher to LEAVE, rather than forcing the flag down
    under it: a live one whose flag has been taken away carries on popping
    work, and the next `run_job` - seeing the flag down - starts a second. Two
    dispatchers on one line take alternate items and run them at the same time,
    which is the whole thing the queue exists to prevent, and it shows up as
    another test failing at random.
    """
    editor.queue_clear()
    end = time.time() + secs
    while editor._Q_RUN["on"] and time.time() < end:
        time.sleep(0.02)
    editor._Q_RUN.update(on=False, qid=0, thread=None)


def _wait(cond, secs=6.0):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_one_action_just_runs(proj):
    seen = []
    editor.run_job(proj, "Cleaning", [0, 1], seen.append)
    assert _wait(lambda: not proj.job["running"] and seen == [0, 1]), seen
    assert editor.queue_state()["count"] == 0


def test_a_second_action_waits_its_turn(proj):
    gate = threading.Event()
    order = []

    def slow(i):
        order.append(("slow", i))
        gate.wait(5)

    editor.run_job(proj, "Cleaning", [0], slow)
    assert _wait(lambda: order)                    # the first one is running
    editor.run_job(proj, "Laying out text", [1, 2],
                   lambda i: order.append(("fast", i)))
    time.sleep(0.2)
    q = editor.queue_state()
    assert q["count"] == 1, q
    assert q["waiting"][0]["label"] == "Laying out text"
    assert q["waiting"][0]["pages"] == 2
    assert order == [("slow", 0)], "the second one started anyway"
    gate.set()
    assert _wait(lambda: order == [("slow", 0), ("fast", 1), ("fast", 2)]), order
    assert editor.queue_state()["count"] == 0


def test_the_line_is_kept_in_order(proj):
    gate = threading.Event()
    order = []
    editor.run_job(proj, "Cleaning", [0], lambda i: gate.wait(5))
    assert _wait(lambda: proj.job["running"])
    for name in ("second", "third", "fourth"):
        editor.run_job(proj, name, [0], lambda i, n=name: order.append(n))
    assert [w["label"] for w in editor.queue_state()["waiting"]] == \
        ["second", "third", "fourth"]
    gate.set()
    assert _wait(lambda: order == ["second", "third", "fourth"]), order


def test_a_waiting_action_can_be_moved(proj):
    gate = threading.Event()
    order = []
    editor.run_job(proj, "Cleaning", [0], lambda i: gate.wait(5))
    assert _wait(lambda: proj.job["running"])
    ids = [editor.run_job(proj, n, [0], lambda i, n=n: order.append(n))
           for n in ("a", "b", "c")]
    assert editor.queue_move(ids[2], -1) is True          # c jumps b
    assert [w["label"] for w in editor.queue_state()["waiting"]] == \
        ["a", "c", "b"]
    assert editor.queue_move(ids[2], -1) is True          # and jumps a
    assert [w["label"] for w in editor.queue_state()["waiting"]] == \
        ["c", "a", "b"]
    gate.set()
    assert _wait(lambda: order == ["c", "a", "b"]), order


def test_it_cannot_be_moved_off_either_end(proj):
    gate = threading.Event()
    editor.run_job(proj, "Cleaning", [0], lambda i: gate.wait(5))
    assert _wait(lambda: proj.job["running"])
    a = editor.run_job(proj, "a", [0], lambda i: None)
    b = editor.run_job(proj, "b", [0], lambda i: None)
    assert editor.queue_move(a, -1) is False, "the head moved up"
    assert editor.queue_move(b, 1) is False, "the tail moved down"
    assert [w["label"] for w in editor.queue_state()["waiting"]] == ["a", "b"]
    gate.set()


def test_a_waiting_action_can_be_dropped(proj):
    gate = threading.Event()
    order = []
    editor.run_job(proj, "Cleaning", [0], lambda i: gate.wait(5))
    assert _wait(lambda: proj.job["running"])
    a = editor.run_job(proj, "a", [0], lambda i: order.append("a"))
    editor.run_job(proj, "b", [0], lambda i: order.append("b"))
    assert editor.queue_drop(a) is True
    assert editor.queue_drop(a) is False, "dropped twice"
    gate.set()
    assert _wait(lambda: order == ["b"]), order


def test_what_is_running_is_not_in_the_line(proj):
    """Cancel stops it mid-page; the queue only holds what has not begun. A
    row that offered to 'remove' the running action would do nothing."""
    gate = threading.Event()
    editor.run_job(proj, "Cleaning", [0], lambda i: gate.wait(5))
    assert _wait(lambda: proj.job["running"])
    q = editor.queue_state()
    assert q["count"] == 0
    assert q["running_qid"] != 0
    assert editor.queue_drop(q["running_qid"]) is False
    gate.set()


def test_an_action_that_fails_stops_the_line(proj):
    """Carrying on would run the next step over pages the last one left
    half-finished, and the green bar would replace the red one before anybody
    had read it."""
    order = []

    def boom(i):
        raise RuntimeError("no")

    editor.run_job(proj, "Cleaning", [0], boom)
    editor.run_job(proj, "Laying out text", [0], lambda i: order.append(i))
    assert _wait(lambda: not proj.job["running"] and proj.job["error"])
    time.sleep(0.3)
    assert order == [], "the queue carried on over a failed run"
    assert editor.queue_state()["count"] == 0
    assert "dropped" in proj.job["error"], proj.job["error"]


def test_cancelling_the_running_one_lets_the_next_start(proj):
    order = []
    started = threading.Event()

    def slow(i):
        started.set()
        order.append(("slow", i))
        time.sleep(0.15)

    editor.run_job(proj, "Cleaning", [0, 1, 2], slow)
    assert started.wait(5)
    editor.run_job(proj, "Laying out text", [0],
                   lambda i: order.append(("fast", i)))
    proj.job["cancel"] = True
    assert _wait(lambda: ("fast", 0) in order), order
    assert proj.job.get("cancelled") is not None
    assert len([o for o in order if o[0] == "slow"]) < 3, "it ran to the end"


def test_the_count_rides_along_with_the_job(proj):
    """One poll, not two. The bar already asks for the job every 700ms while
    something is running; the button reads its number off the same answer."""
    from pathlib import Path
    src = (PKG
           / "editor.py").read_text(encoding="utf8")
    assert 'j["queue"] = queue_state()' in src
    js = (PKG / "static" / "js"
          / "pipeline.js").read_text(encoding="utf8")
    assert "if(j.queue) paintQueue(j.queue)" in js


def test_the_poll_keeps_going_while_anything_is_waiting(proj):
    """It used to stop the moment the running job finished. With a queue that
    would leave the bar on 'Ready' while three more actions ran behind it."""
    from pathlib import Path
    js = (PKG / "static" / "js"
          / "pipeline.js").read_text(encoding="utf8")
    assert "j.running || (j.queue && j.queue.count)" in js


def test_clearing_the_line_stops_what_had_not_started(proj):
    gate = threading.Event()
    order = []
    editor.run_job(proj, "Cleaning", [0], lambda i: gate.wait(3))
    assert _wait(lambda: proj.job["running"])
    editor.run_job(proj, "next", [0], lambda i: order.append("next"))
    assert editor.queue_clear() == 1
    gate.set()
    time.sleep(0.4)
    assert order == [], "a dropped action ran anyway"
    assert editor._Q_RUN["on"] is False, "the dispatcher kept the flag"
    # ...and a fresh one still starts
    editor.run_job(proj, "after", [0], lambda i: order.append("after"))
    assert _wait(lambda: order == ["after"]), order


def test_a_dispatcher_reports_into_the_project_the_work_came_from(proj):
    """One global queue, and the editor is handed a new project whenever one
    is opened. A dispatcher that captured the project it started with would
    write its progress into a project nobody is looking at any more - and
    under the test suite, where one project follows another through the same
    module, it did exactly that."""
    import shutil
    from mangatl.project import Project
    other_root = scratch("_tmp_queue2")
    shutil.rmtree(other_root, ignore_errors=True)
    other = Project(None, other_root)
    for k in range(2):
        other.add_uploaded(f"q{k}.png",
                           cv2.imencode(".png", np.full((80, 60, 3), 240,
                                                        np.uint8))[1].tobytes())
    try:
        gate = threading.Event()
        editor.run_job(proj, "Cleaning", [0], lambda i: gate.wait(3))
        assert _wait(lambda: proj.job["running"])
        editor.run_job(other, "Laying out text", [0, 1], lambda i: None)
        gate.set()
        assert _wait(lambda: other.job.get("total") == 2), other.job
        assert other.job["label"] == "Laying out text"
        assert proj.job["label"] == "Cleaning", proj.job
    finally:
        # Wait for it to actually STOP before the folder goes. Asserting on the
        # progress and then deleting the pages out from under a dispatcher that
        # is still working left a thread reading a file that no longer existed
        # - which surfaced as a different test failing, later, at random.
        editor.queue_clear()
        _wait(lambda: not editor._Q_RUN["on"] and not other.job.get("running")
              and not proj.job.get("running"), 8.0)
        shutil.rmtree(other_root, ignore_errors=True)



def test_the_next_action_starts_when_the_one_before_it_finishes(proj):
    """lee: *"i hit clean and had translate in teh queue but when clean ws done
    nothing happend"*.

    The exact shape: a long action running, a second one put in the line while
    it runs, and the line has to carry on by itself when the first one ends.
    """
    gate = threading.Event()
    order = []
    editor.run_job(proj, "Cleaning", [0], lambda i: (order.append("clean"),
                                                     gate.wait(5)))
    assert _wait(lambda: order == ["clean"])
    editor.run_job(proj, "Translating", [0, 1],
                   lambda i: order.append(f"tr{i}"))
    gate.set()
    assert _wait(lambda: order == ["clean", "tr0", "tr1"], 8), order
    assert editor.queue_state()["count"] == 0


def test_a_flag_left_up_by_a_dead_dispatcher_does_not_strand_the_line(proj):
    """The flag says "a dispatcher is on it". Every way of leaving it up on the
    way out - a raise between two turns of the lock, a thread that died - used
    to strand everything queued behind it for ever, and from outside that is a
    Clean that finished and a Translate that never began.

    So the flag is checked against the thread that made it. This is the state
    the bug left behind; nothing may sit in it."""
    order = []
    editor._Q_RUN.update(on=True, qid=0, thread=None)   # claimed by nobody
    editor.run_job(proj, "Translating", [0], lambda i: order.append(i))
    assert _wait(lambda: order == [0], 6), order


def test_a_dispatcher_that_died_is_replaced(proj):
    order = []
    dead = threading.Thread(target=lambda: None)
    dead.start(); dead.join()
    editor._Q_RUN.update(on=True, qid=0, thread=dead)
    editor.run_job(proj, "Translating", [0], lambda i: order.append(i))
    assert _wait(lambda: order == [0], 6), order


def test_a_live_dispatcher_is_not_doubled(proj):
    """Two dispatchers on one line would take alternate items and run them at
    the same time, which is the whole thing the queue exists to prevent."""
    gate = threading.Event()
    started = []
    editor.run_job(proj, "Cleaning", [0], lambda i: (started.append(1),
                                                     gate.wait(5)))
    assert _wait(lambda: started)
    at_once = []
    for name in ("a", "b", "c"):
        editor.run_job(proj, name, [0],
                       lambda i, n=name: at_once.append(n))
    gate.set()
    assert _wait(lambda: at_once == ["a", "b", "c"], 8), at_once


def test_the_line_survives_an_action_that_finishes_with_an_error(proj):
    """The error path puts the flag down and clears the line in one turn of the
    lock. In two, an action arriving in the middle joins a line nobody is
    coming back for."""
    editor.run_job(proj, "Cleaning", [0],
                   lambda i: (_ for _ in ()).throw(RuntimeError("no")))
    # ...and wait for the DISPATCHER to be done with it, not just for the
    # error to appear: the error is set inside the run, and putting the flag
    # down is the next thing that happens.
    assert _wait(lambda: proj.job.get("error") and not editor._Q_RUN["on"],
                 6), (proj.job, editor._Q_RUN)
    order = []
    editor.run_job(proj, "after", [0], lambda i: order.append("after"))
    assert _wait(lambda: order == ["after"], 6), order


def test_an_action_arriving_as_the_line_is_torn_down_still_runs(proj):
    """A failed run drops what was waiting and puts the flag down. If those are
    two separate turns of the lock there is a gap between them, and an action
    that arrives in the gap sees the flag still up - with the dispatcher still
    alive, so the liveness check passes too - joins a line that is being
    abandoned, and waits for somebody who has already gone home.

    Widened here to something a test can hit: the teardown is made slow, and an
    action is sent during it.
    """
    slow = threading.Event()
    real = editor.queue_clear

    def dawdle():
        n = real()
        slow.set()
        time.sleep(0.6)          # the gap, made big enough to aim at
        return n

    editor.queue_clear = dawdle
    order = []
    try:
        editor.run_job(proj, "Cleaning", [0],
                       lambda i: (_ for _ in ()).throw(RuntimeError("no")))
        # ...arrive while the line is coming down
        if slow.wait(4):
            time.sleep(0.05)
        editor.run_job(proj, "after", [0], lambda i: order.append("after"))
    finally:
        editor.queue_clear = real
    assert _wait(lambda: order == ["after"], 8), (order, editor._Q_RUN,
                                                  editor.queue_state())


def test_the_page_is_brought_up_to_date_as_each_action_ends(proj):
    """lee: *"when the translat e finishes the cleanig aslso showed up"*.

    The page on screen was refreshed only when the whole line was empty. With
    Clean running and Translate waiting behind it, the cleaned art therefore
    did not appear until the translation had finished as well - two actions'
    worth of work arriving at once, long after the first one was done.
    """
    from pathlib import Path
    js = (PKG / "static" / "js"
          / "pipeline.js").read_text(encoding="utf8")
    # the refresh happens on the branch that still has work waiting
    at = js.index("if(j.running || (j.queue && j.queue.count))")
    end = js.index("setTimeout(poll,700); return; }", at)
    branch = js[at:end]
    assert "showPage(cur)" in branch, branch
    assert "changed" in branch, branch


def test_it_is_one_refresh_per_action_not_one_per_poll(proj):
    """A poll every 700ms rebuilding the page would make the whole run
    unusable - the refresh is hung on the running action CHANGING."""
    from pathlib import Path
    js = (PKG / "static" / "js"
          / "pipeline.js").read_text(encoding="utf8")
    assert "poll._at !== nowRunning" in js
    assert "j.queue.running_qid" in js, \
        "the label alone cannot tell two Cleans apart"
