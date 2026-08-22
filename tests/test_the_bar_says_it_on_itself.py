"""The words live ON the progress bar, not in a line above it.

lee asked for the loading bar to be redesigned and to be shown the options
first: *"redesgn the loading bar and sow me picture befor implimenting and let
me choose fro deferent ones"*. Five were drawn - a cell per page, a solid bar
with the words on it, a ring, a full-width hairline, and the step button
filling - and he picked the solid bar.

What was wrong with the old one: 6px of hairline under 11px of grey. It said
how far and nothing else, its gradient flowed whether or not anything was
happening, and at 4% it looked like it did at 96%.

The new one is 26px, carries the step and the count inside it, keeps the
percentage in its own slot on the right, and only marches while a run is
running. It costs no width: `.jobcol` is the same fixed 250px, because the
line of text that used to sit above the bar now sits inside it.
"""
import re

import pytest

from where import PKG

CSS = (PKG / "static" / "css" / "editor.css").read_text("utf-8")
HTML = (PKG / "static" / "editor.html").read_text("utf-8")
JS = (PKG / "static" / "js" / "pipeline.js").read_text("utf-8")


def _rule(sel):
    """The rule whose selector is exactly this - anchored at the start of a
    line, or `#bar` would find `.barrow #bar` and read the wrong one."""
    m = re.search(r"(?m)^" + re.escape(sel) + r"\{([^}]*)\}", CSS, re.S)
    assert m, f"{sel} must be styled"
    return m.group(1).replace("\n", "").replace(" ", "")


def test_the_words_are_inside_the_bar():
    at = HTML.index('id="bar"')
    bar = HTML[at:HTML.index("</div>", HTML.index('id="jobpct"'))]
    assert 'id="fill"' in bar
    assert 'id="jobtxt"' in bar, "the label sits on the bar, not above it"
    assert 'id="jobpct"' in bar


def test_the_bar_is_tall_enough_to_read_words_on():
    rule = _rule("#bar")
    m = re.search(r"height:(\d+)px", rule)
    assert m and int(m.group(1)) >= 20, rule
    assert "position:relative" in rule, "the label is laid over the fill"


def test_the_percentage_has_its_own_slot():
    """It came out of the sentence, which is what buys the room: the words and
    the number used to share one 250px line."""
    assert "#jobpct" in CSS
    body = JS.split("function paintJob(j, pct)", 1)[1].split("\nfunction ", 1)[0]
    assert "$('jobpct')" in body
    assert "pages (${pct}%)" not in body, "the number left the sentence"
    assert "${j.done} of ${j.total}" in body, "...and the page count did not"


def test_the_bar_says_the_step_and_not_the_running_commentary():
    """lee, with a crop of it: *"remove the explation for the loading bar, it
    shoud just say reading tetx or finsinhg text or tralstion etc"*.

    A step writes its progress into the same field it is NAMED by, so
    `job.label` arrives as "Reading text - AI reader, piece 17 of 23...". The
    bar showed all of it, cut with an ellipsis, and the name - the one thing
    somebody actually reads across the room - was the part that survived."""
    assert "function stepName(label)" in JS
    body = JS.split("function paintJob(j, pct)", 1)[1].split("\nfunction ", 1)[0]
    assert "${stepName(j.label)}" in body
    assert "${j.label}" not in body, "the whole sentence never reaches the bar"


def test_the_step_button_lights_while_its_run_is_talking():
    """The same bug, in the other place that reads that field: `renderSteps`
    lights a step by comparing it to the step's own job name, so a step in the
    middle of saying anything at all matched nothing and went dark."""
    at = JS.index("renderSteps(j.running")
    assert "stepName(j.label)" in JS[at:at + 80], JS[at:at + 80]


def test_the_name_is_everything_before_the_dash():
    """Both dashes: the say() messages use an em dash, and a couple of older
    ones a spaced hyphen."""
    body = JS.split("function stepName(label)", 1)[1].split("\n}", 1)[0]
    assert "\\u2014" in body or "\u2014" in body
    assert "' - '" in body
    assert ".trim()" in body


def test_the_percentage_is_only_shown_when_there_is_a_run_to_measure():
    """A percentage beside "Ready" is a number about nothing."""
    body = JS.split("function paintJob(j, pct)", 1)[1].split("\nfunction ", 1)[0]
    at = body.index("$('jobpct')")
    tail = body[at:at + 200]
    assert "j.running" in tail and "loading_model" in tail


def test_only_a_running_job_marches():
    """The one thing on the strip that means "still going". The old bar
    flowed its gradient whether or not anything was happening, so a stalled
    run looked exactly like a working one."""
    assert "#job.busy #fill::after" in CSS
    assert "@keyframes march" in CSS
    # ...and the plain fill has no animation of its own
    assert "animation" not in _rule("#fill")


def test_loading_the_models_paces_instead_of_inventing_a_number():
    """No pages in it to count, so the fill slides. Same answer the File tab's
    bar gives to the same question."""
    assert "#bar.wait #fill" in CSS
    assert "@keyframes slide" in CSS
    body = JS.split("function paintJob(j, pct)", 1)[1].split("\nfunction ", 1)[0]
    assert "classList.toggle('wait'" in body
    assert "'35%'" in body, "the width is set with the class, not by it"


def test_the_label_is_readable_over_the_fill_and_over_the_dark():
    """This text crosses the fill's own edge - amber on one side of it,
    near-black on the other - so one flat colour cannot be read on both."""
    m = re.search(r"#job\.busy #jobtxt[^{]*\{([^}]*)\}", CSS, re.S)
    assert m, "the running label needs its own colour"
    rule = m.group(1).replace("\n", "").replace(" ", "")
    assert "color:#fff" in rule
    assert "text-shadow" in rule


def test_the_warning_is_dark_ink_on_its_orange_bar():
    """`#job.warn #fill` fills the whole bar orange. Orange words on it are
    not a warning, they are a blank."""
    assert "#job.warn #fill" in CSS
    rule = _rule("#job.warn #jobtxt")
    assert "var(--warn)" not in rule, rule
    assert rule.startswith("color:#"), rule


def test_idle_is_grey_rather_than_a_dim_amber():
    """`paintJob` leaves the fill at 100% when nothing is running, so the bar
    is full. Amber at low opacity over a near-black bar came out olive."""
    assert "#job.idle #fill" in CSS
    rule = _rule("#job.idle #fill")
    assert "background:#" in rule, rule
    assert "opacity" not in rule, "dimming the bar takes the label with it"


def test_the_whole_bar_is_what_you_click():
    """The message used to hang off the line of text. That line is inside the
    bar now, and the label layer does not take the click."""
    assert 'id="bar" onclick="showJobMessage()"' in HTML
    assert "pointer-events:none" in _rule(".joblab")


def test_the_file_tab_bar_still_has_its_flow():
    """`@keyframes flow` was the job bar's; the File tab's bar still uses it
    and deleting it would have stopped that one animating."""
    assert "@keyframes flow" in CSS
    assert "animation:flow" in CSS


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
