"""Half the sound-effect boxes had no writing in them.

lee's chapter 1, all 67 pages, every box the detector drew - 194 of them, and
each one looked at. **18 of the 36 boxes it called a sound effect were on
artwork**: sword blades, a face, two buildings, clothing, a gold ornament, a
leg, a bed, and five times on the little trailing ellipses of a thought
balloon's tail.

That is the coverage pass. It keeps whatever ink the segmentation mask left
over once the block head has had its turn, and the mask fires on a drawn line
as happily as on a written one.

**Six cheap ways of telling writing from drawing were measured on those 36
boxes and not one of them separates** - number of marks, how even the marks are
in size, ink density, how thin the longest stroke is, how many holes it has,
which pass made the box. The two distributions sit on top of each other in
every one. This is the useful negative result: the leftover mask ink genuinely
looks like writing by every statistic that does not know what writing is.

What does separate them is asking something trained on writing. CRAFT is
already here for the other half of the job, so it is one more question per page
and no new dependency:

    16 of 18 artwork boxes    CRAFT sees NOTHING in them
     2 of 18 artwork boxes    0.10 and 0.19 of the box covered
    17 of 18 real effects     0.07 to 0.53

So the bar is any overlap at all. Not a fraction - a fraction would be a number
to tune and the measurement will not support one, with real effects down at
0.07 and two artwork boxes up at 0.19.

**What it costs.** One real effect in eighteen: page 036's 휘잉, a thin
hand-drawn vertical scrawl on pale paper, scored 0.000 - and still 0.000 with
CRAFT's `low_text` swept down to 0.15, so no amount of generosity recovers it.
A veto can afford to be generous where a detector cannot, and it was tried:

    low_text 0.50   vetoes 16 of 18 junk, loses 1 of 18 real   <- here
    low_text 0.35   vetoes 13 of 18
    low_text 0.25   vetoes 12 of 18
    low_text 0.15   vetoes 11 of 18

lee: *"Missed SFX is worse"* than a box to delete. So this is a setting he owns
and not a law, and it is on by default because 16 gone for 1 lost is the better
default - not because losing one is fine.

**Run for real over the whole chapter, it does exactly that and no more.** 257
boxes with the switch off, 240 with it on: 16 artwork boxes gone, one real
effect gone, nothing added, nothing outside the coverage pass touched. The two
artwork boxes CRAFT does see survive, as measured.

**An earlier version of this file claimed the veto also added nine boxes, seven
of them real effects.** That was wrong, and the reason is worth keeping. The
"before" it was measured against had been recorded before easyocr was installed
in the container, so CRAFT contributed nothing to it - seven of those nine were
boxes CRAFT adds with the veto on or off. A before-and-after has to move one
thing, and that one did not.
"""
import numpy as np
import pytest

from mangatl.detect import comictext as CT


INPUT = CT.INPUT


class _Net:
    """comic-text-detector, minus the 95MB and the neural net.

    Returns no blocks and a mask with one patch of writing on it, so
    everything the real function does after the block head runs for real: the
    letterbox arithmetic, the mask resize, `_harvest`, and the veto.
    """

    def __init__(self, patches):
        self.patches = patches

    def setInput(self, blob):
        pass

    def getUnconnectedOutLayersNames(self):
        return ["blk", "seg"]

    def forward(self, names):
        blk = np.zeros((1, 1, 6), np.float32)      # one box, confidence 0
        seg = np.zeros((1, 1, INPUT, INPUT), np.float32)
        for x0, y0, x1, y1 in self.patches:
            seg[0, 0, y0:y1, x0:x1] = 1.0
        return [blk, seg]


def _fake_craft(monkeypatch, boxes, ok=True):
    """Stand in for `detect/craft.py`, without easyocr or a 95MB download.

    Both the `sys.modules` entry AND the attribute on the package, because
    `from . import craft` prefers the attribute when some earlier test has
    already imported the real thing - which is why the first version of this
    passed alone and failed under `-n 4`, in whichever worker happened to have
    touched CRAFT first.
    """
    import sys
    import types

    import mangatl.detect as _pkg

    mod = types.ModuleType("mangatl.detect.craft")
    mod.available = lambda: ok
    mod.pieces = lambda img, **kw: list(boxes)
    mod.group = lambda pieces, x, y: []
    mod.merge_into = lambda *a, **kw: []
    monkeypatch.setitem(sys.modules, "mangatl.detect.craft", mod)
    monkeypatch.setattr(_pkg, "craft", mod, raising=False)
    return mod


def _run(monkeypatch, craft_boxes, ok=True, second_opinion=True, side=1024):
    """One square page with a patch of mask ink in the middle of it."""
    from mangatl.models import Page

    # A square page letterboxes to nothing, so the mask patch lands where it
    # was put. 400..600 of 1024 is the middle fifth.
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net([(400, 400, 600, 600)]))
    _fake_craft(monkeypatch, craft_boxes, ok)
    page = Page(image=np.zeros((side, side, 3), np.uint8))
    return CT.detect_comictext(page, "no-such-model.onnx",
                               mask_thresh=0.2, join_x=1.8, join_y=0.9,
                               craft_x=0.30, craft_y=0.05,
                               classify=False,
                               second_opinion=second_opinion)


# ---------------------------------------------------------------- the rule

def test_a_box_craft_sees_nothing_in_is_refused():
    assert CT._seen_by([(500, 500, 560, 560)], 10, 10, 100, 100) is False


def test_any_overlap_at_all_is_enough():
    """The bar is not a fraction. Real effects go down to 0.07 of the box and
    two artwork boxes CRAFT DOES see go up to 0.19, so there is no fraction the
    36 measured boxes would support."""
    assert CT._seen_by([(95, 95, 400, 400)], 10, 10, 100, 100) is True


def test_both_rectangles_include_their_far_edge():
    """`_harvest` returns the last row and column of the ink and CRAFT returns
    polygon corners, so a piece ending on the box's first column shares one
    column of pixels with it - an overlap. One pixel clear of it is not."""
    assert CT._seen_by([(0, 10, 10, 100)], 10, 10, 100, 100) is True
    assert CT._seen_by([(0, 10, 9, 100)], 10, 10, 100, 100) is False
    assert CT._seen_by([(100, 10, 200, 100)], 10, 10, 100, 100) is True
    assert CT._seen_by([(101, 10, 200, 100)], 10, 10, 100, 100) is False


def test_the_other_axis_is_checked_too():
    """Overlapping in x is half an answer. A caption directly above a sound
    effect shares every column with it and none of its rows."""
    assert CT._seen_by([(10, 200, 100, 300)], 10, 10, 100, 100) is False
    assert CT._seen_by([(10, 0, 100, 9)], 10, 10, 100, 100) is False
    assert CT._seen_by([(10, 100, 100, 300)], 10, 10, 100, 100) is True


def test_the_axes_are_not_crossed():
    """Every other fixture here is square enough that swapping x for y gives
    the same answer. A tall narrow box with a wide flat piece well off to the
    side of it does not: crossed, the piece's width is compared against the
    box's height and it comes back seen."""
    tall = (10, 10, 30, 200)
    assert CT._seen_by([(100, 15, 400, 25)], *tall) is False
    assert CT._seen_by([(12, 15, 25, 25)], *tall) is True


def test_it_stops_at_the_first_piece_that_sees_it():
    """A page has hundreds of CRAFT pieces and this runs per box."""
    seen = []

    class Watch(list):
        def __iter__(self):
            for v in list.__iter__(self):
                seen.append(v)
                yield v

    CT._seen_by(Watch([(10, 10, 100, 100), (500, 500, 600, 600)]),
                20, 20, 50, 50)
    assert len(seen) == 1


def test_nothing_is_refused_on_an_empty_opinion():
    assert CT._seen_by([], 10, 10, 100, 100) is False


# ----------------------------------------------------- and where it is used

def test_the_box_is_kept_when_craft_sees_the_writing(monkeypatch):
    """The fixture first, without the veto doing anything, so a test that
    passes below because NOTHING was ever found cannot hide here."""
    got = _run(monkeypatch, [(420, 420, 580, 580)])
    assert len(got) == 1 and got[0].kind == "sfx", [r.kind for r in got]


def test_the_box_is_refused_when_craft_sees_nothing(monkeypatch):
    """The same page, the same mask, CRAFT looking somewhere else."""
    assert _run(monkeypatch, [(20, 20, 60, 60)]) == []


def test_turning_it_off_keeps_the_box(monkeypatch):
    """lee's switch. Same page, same blind CRAFT, veto off."""
    got = _run(monkeypatch, [(20, 20, 60, 60)], second_opinion=False)
    assert len(got) == 1


def test_nothing_is_refused_when_easyocr_is_missing(monkeypatch):
    """A veto needs an opinion. With easyocr absent, or on a format that does
    not run CRAFT, nothing may be refused - silently dropping every sound
    effect because an optional dependency is missing is the worst outcome
    available, and it would look exactly like the detector getting worse."""
    got = _run(monkeypatch, [(20, 20, 60, 60)], ok=False)
    assert len(got) == 1


def test_nothing_is_refused_when_the_format_does_not_run_craft(monkeypatch):
    """Manga has `craft_x`/`craft_y` at None. There is no second opinion to be
    had, so the coverage pass keeps what it always kept."""
    from mangatl.models import Page

    monkeypatch.setattr(CT, "_get_net", lambda p: _Net([(400, 400, 600, 600)]))
    _fake_craft(monkeypatch, [])
    got = CT.detect_comictext(Page(image=np.zeros((1024, 1024, 3), np.uint8)),
                              "no-such-model.onnx", mask_thresh=0.2,
                              classify=False, second_opinion=True)
    assert len(got) == 1


def test_the_block_heads_own_boxes_are_never_refused():
    """The veto sits in the COVERAGE pass only. The block head is the best
    thing here at dialogue - CRAFT was brought in to add to it, not to overrule
    it - and a balloon CRAFT happened to miss must not vanish."""
    import inspect

    src = inspect.getsource(CT.detect_comictext)
    veto = src.index("if second_opinion and craft_pieces is not None")
    harvest = src.index("for (x0, y0, x1, y1), sub, ink in _harvest(")
    blocks = src.index("for x1, y1, x2, y2, cf in _decode_blocks(")
    assert blocks < harvest < veto, "the veto moved out of the coverage pass"


def test_craft_is_only_run_once_a_page():
    """The veto and the second detector's own pass want the same pieces, and
    CRAFT is the slowest thing here. Asking twice would double it."""
    import inspect

    src = inspect.getsource(CT.detect_comictext)
    # Started once at the top of the run and collected once further down. It
    # is handed to a worker now rather than called in place, so the thing to
    # count is the submission -- see
    # `test_the_two_detectors_are_running_at_the_same_time`.
    assert src.count("_POOL.submit(_craft.pieces,") == 1
    assert src.count("_craft.pieces(img)") == 0, "back to a blocking call"
    assert src.count("craft_job.result()") == 1
    assert "_craft.group(craft_pieces," in src


def test_the_setting_reaches_the_detector():
    import inspect

    from mangatl import project

    src = inspect.getsource(project.Project._detect_measured)
    assert 'second_opinion=self.settings.get("sfx_second_opinion", True)' in src


def test_the_setting_defaults_on():
    import inspect

    from mangatl import project

    src = inspect.getsource(project.Project)
    assert '"sfx_second_opinion": True,' in src


def test_the_switch_is_not_on_the_page_any_more():
    """It had a tick beside `auto_kind`. lee: *"remove this"*.

    He is right: sound effects are not offered at all on manhwa and manhua
    now, so on the very format this veto was measured for, the switch decides
    what happens to boxes that are filtered out either way. A setting whose
    only visible effect is on a format it was never measured on is a setting
    to get wrong.

    Still READ, though - see the test below. A project.json that turned it off
    is still obeyed, and putting the tick back is one line of HTML.
    """
    from where import PKG

    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert 'id="sfx_second_opinion"' not in html
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert "sfx_second_opinion" not in js


def test_a_project_that_turned_it_off_is_still_obeyed():
    """With the tick gone the setting is Python-side only, and it has to keep
    working - otherwise removing a control silently changed what every project
    that used it does."""
    import inspect

    from mangatl import project

    src = inspect.getsource(project.Project._detect_measured)
    assert 'second_opinion=self.settings.get("sfx_second_opinion", True)' in src
    assert '"sfx_second_opinion": True,' in inspect.getsource(project.Project)
