"""Untick Sound effect and the second detector should not run at all.

lee: *"i also want to make it so that if sfx are not selectd to be detected
craft shoud not run"*.

He is asking for the largest saving anywhere in Find text. CRAFT is **93% of
the run** -- 8 seconds of a 9 -- and with the tick off almost everything it
contributes was being thrown away by `only_kinds` a moment later. The three
ticks in the dialog steer the measuring detectors and walked straight past
this one, because CRAFT was hung off the FORMAT (manhwa and manhua, never
manga) rather than off the choice.

Measured over twelve pages with Bubble text and Outside text ticked and Sound
effect not:

    CRAFT still running   107.7s   8.97s a page   26 boxes
    CRAFT skipped          49.4s   4.12s a page   26 boxes

**2.18x**, and the same number of boxes.

## What it is not: free

Ten of the twelve pages come back identical. Two do not, and the reason is
worth writing down because it contradicts the obvious assumption.

`merge_into` labels everything it adds `sfx`, so it looks as though CRAFT can
only ever produce sound effects -- but `loose_bubble` and `_classify_kind` run
afterwards and can relabel one. On **012** the credits line is a box only
CRAFT saw, and by the end of the run it is *outside text*, so skipping CRAFT
loses it. On **010** the opposite: a CRAFT sound effect was suppressing a
small piece of outside text, and skipping CRAFT lets it through.

So the tick is not purely a speed control -- with it off, a couple of boxes
that only the second detector could find go with it. That is the honest
trade for halving the run, and it is what lee asked for.
"""
import inspect

import pytest

from where import PKG

from mangatl.detect import comictext as CT


def test_find_text_can_be_told_nobody_wants_effects():
    sig = inspect.signature(CT.detect_comictext)
    assert "want_sfx" in sig.parameters
    # ...and a caller that has not heard of it gets the run lee measured.
    assert sig.parameters["want_sfx"].default is True


def test_the_second_detector_is_gated_on_the_tick():
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    assert "if craft_x and craft_y and want_sfx:" in src


def test_the_tick_reaches_the_detector_from_the_project():
    src = (PKG / "project.py").read_text(encoding="utf-8")
    assert 'want_sfx=("sfx" in kinds)' in src


def test_it_is_the_choice_and_not_the_format():
    """Both still have to hold. The format decides whether CRAFT is any use
    on this kind of comic -- manga's tuning has no reach at all and never
    calls it -- and the tick decides whether anybody wants what it finds."""
    assert CT.tuning_for("manga")["craft_x"] is None
    assert CT.tuning_for("manhwa")["craft_x"] == 0.30
    assert CT.tuning_for("manhua")["craft_x"] == 0.30


def test_asking_for_effects_still_runs_it(monkeypatch):
    """The gate is only a gate. With the tick on, nothing changed."""
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    i = src.index("if craft_x and craft_y and want_sfx:")
    j = src.index("craft_job = _POOL.submit", i)
    assert j - i < 400, "the submit must still be inside that branch"


def test_the_saving_and_its_price_are_recorded():
    """Both halves. A reader who finds this later needs to know it is 2.18x
    AND that 012's credits line goes with it."""
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    assert "93%" in src
    assert "only_kinds" in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
