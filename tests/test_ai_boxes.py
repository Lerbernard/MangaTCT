"""The AI box pass is gone, and this file is what stops it coming back by
accident.

There were 1682 lines of tests here for it: the prompt, the two fences that made
"it cannot move a box" arithmetic rather than a request, the labelled PNG, the
find mode, and all the geometry that existed to turn a model's loose rectangle
into a box round actual ink. lee watched the pass run on his own chapter: "nvm
remove it its pretty bad remove the ai". mangatl/aiboxes.py is now a note saying
so, and every test that poked at it went with it.

Two things are left, and both are load-bearing.

FIRST, the guard. Find text is measurement only, and the tests below fail if any
part of the pass is wired back in: if Project.detect learns the word aiboxes
again, if an "ai_boxes" setting reappears among the defaults, if the _ai_mode /
_can_ask / _ai_ctx helpers come back onto Project, if the editor grows the menu
again, or if aiboxes.py stops being an empty note. None of that is forbidden
forever — it is forbidden silently. Re-adding it means coming here and saying out
loud that it is being re-added.

Nothing here touches the AI READER, the translator, the proofreader or the hosted
cleaner. Those were never part of this and are all still on; there is a test
below that says so, because "remove the ai" is a sentence that could be read far
too widely by somebody tidying up later.

SECOND, only_kinds(). It lives in project.py and this was the only file that
tested it, so its three tests are carried over unchanged rather than deleted with
everything else. They are the reason this file still imports cv2 and TextRegion.
"""
import ast
import inspect
import pathlib

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.models import TextRegion
from where import PKG

ROOT = PKG


def _region(bbox, rid=0, kind="freefloat", **kw):
    x, y, w, h = bbox
    return TextRegion(
        id=rid, bbox=bbox, bubble_bbox=bbox,
        polygon=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        kind=kind, **kw)


# ------------------------------------------------------- the pass is gone

def test_finding_text_never_mentions_the_ai_box_pass():
    """The whole of Find text, read as source: the detectors it calls, the
    kinds it keeps, the grouping at the end. If the word aiboxes appears
    anywhere in it the pass has a turn again, whatever the settings say."""
    from mangatl import project

    src = inspect.getsource(project.Project.detect)
    low = src.lower()
    for word in ("aiboxes", "ai_boxes", "_ai_mode", "_can_ask", "judge_boxes",
                 "find_boxes", "apply_verdict"):
        assert word not in low, word


def test_no_module_imports_the_removed_pass():
    """Not just detect — nothing in the package. An import somewhere else
    would mean a second door into it."""
    hits = []
    for f in sorted(ROOT.rglob("*.py")):
        if f.name == "aiboxes.py":
            continue
        # The suite lives inside the package, so an unfiltered walk finds this
        # very file — which imports the module on purpose, one test down, to
        # prove there is nothing left in it. What is being asked here is about
        # the code that SHIPS: a test reaching for a dead module is a test, and
        # an app reaching for one is a second door into it.
        if "tests" in f.parts:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if "aiboxes" in a.name:
                        hits.append(f"{f.name}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                if "aiboxes" in (node.module or ""):
                    hits.append(f"{f.name}:{node.lineno}")
                for a in node.names:
                    if a.name == "aiboxes":
                        hits.append(f"{f.name}:{node.lineno}")
    assert hits == []


def test_the_module_that_held_it_holds_nothing():
    """aiboxes.py is left on disk as a note, because nothing here can delete a
    file on lee's machine. A note is all it may be: if it grows a function
    again, something is being rebuilt inside a file whose whole text says it
    was removed."""
    from mangatl import aiboxes

    tree = ast.parse(pathlib.Path(aiboxes.__file__).read_text(encoding="utf-8"))
    kept = [n for n in tree.body if not (isinstance(n, ast.Expr)
                                         and isinstance(n.value, ast.Constant))]
    assert kept == [], [type(n).__name__ for n in kept]
    public = [n for n in vars(aiboxes) if not n.startswith("_")]
    assert public == [], public


def test_nothing_on_a_project_is_left_over_from_the_pass():
    """Three helpers fed it — _ai_ctx, _ai_mode, _can_ask — and none of them
    had another caller. The reader and the translator put the backend onto
    self.ctx themselves, in editor.py."""
    from mangatl.project import Project

    for name in ("_ai_mode", "_can_ask", "_ai_ctx"):
        assert not hasattr(Project, name), name


def test_a_fresh_project_has_no_setting_for_it(tmp_path):
    from mangatl.project import Project

    p = Project(None, str(tmp_path / "out"))
    assert "ai_boxes" not in p.settings
    assert p.settings["auto_kind"] is True   # measurement's own labelling stays


def test_an_old_project_carrying_the_setting_loads_and_is_unchanged(tmp_path):
    """lee's project.json on disk still has "ai_boxes": "check" in it. It has
    to be a dead word, not a crash and not a switch — loading it must neither
    fail nor turn anything on."""
    import json
    from mangatl.project import Project

    out = tmp_path / "out"
    out.mkdir()
    (out / "project.json").write_text(json.dumps(
        {"settings": {"ai_boxes": "check", "auto_kind": True}, "pages": []}),
        encoding="utf-8")
    p = Project(None, str(out))
    assert p.settings.get("ai_boxes") == "check"   # carried, not read
    src = inspect.getsource(Project.detect)
    assert "ai_boxes" not in src


def test_the_editor_offers_no_menu_for_it():
    """The control lee used to pick this with is gone from the page, so there
    is nothing to save even if the backend grew the setting back."""
    html = (ROOT / "static" / "editor.html").read_text(encoding="utf-8")
    assert 'id="ai_boxes"' not in html
    js = (ROOT / "static" / "js" / "project.js").read_text(encoding="utf-8")
    body = js.partition("function saveSettings")[2]
    assert "ai_boxes" not in body


def test_the_other_ai_is_all_still_here(tmp_path):
    """"remove the ai" meant the box pass, which lee had just watched be bad at
    its job. It did not mean the reader, the translator, the proofreader or the
    cleaner — those are the ones that earn their keep, and a later tidy-up
    reading that sentence more widely than it was meant would gut the app."""
    from mangatl import editor, inpaint, ocr, translate
    from mangatl.project import Project

    assert callable(ocr.ocr_page)                  # the reader
    assert callable(translate.build_payload)       # the translator
    assert callable(translate.proofread_page)      # the proofreader
    assert callable(editor.clean_page)             # the cleaning stage
    assert callable(inpaint.inpaint_page)          # and what it paints with
    # And the hosted (AI) cleaner in particular, which is the one that costs
    # money and is therefore the one somebody might rip out while "removing
    # the ai": its setting is still among the defaults.
    # In `tmp_path`, because `Project` MAKES its output directory. This used
    # to pass `/nonexistent-so-nothing-is-written`, on the theory that the name
    # would keep it from being written — and a name is not a permission. Run as
    # root the directory was quietly created at the root of the filesystem on
    # every run; run as anybody else, as CI is, it was a PermissionError.
    p = Project(None, str(tmp_path / "defaults"))
    assert "ai_clean" in p.settings
    assert "clean_url" in p.settings


# ------------------------------------ the kinds the person actually asked for
#
# only_kinds() belongs to project.py and this was the only file testing it, so
# these three came through the removal untouched.

def test_a_caption_answers_to_the_box_for_speech_and_narration():
    """It used to answer to "text outside bubbles", on the grounds that it
    stands outside a balloon. lee renamed the first checkbox to "speech and
    narration bubble", which moves it: a caption is a box with dialogue in it,
    read in the reading order and typeset like speech, and the loose text lying
    on the artwork is the group it has least in common with."""
    from mangatl.project import only_kinds

    caption = _region((10, 10, 30, 30), kind="narration")
    assert only_kinds([caption], ["bubble"]) == [caption]
    assert only_kinds([caption], ["freefloat"]) == []
    assert only_kinds([caption], ["sfx"]) == []


def test_a_kind_nobody_named_is_never_thrown_away():
    """lee can add his own kinds in the settings. Not being one of the four
    the dialog knows about is no reason to lose the box."""
    from mangatl.project import only_kinds

    odd = _region((10, 10, 30, 30), kind="signpost")
    assert only_kinds([odd], ["bubble"]) == [odd]


def test_asking_for_nothing_in_particular_keeps_everything():
    from mangatl.project import only_kinds

    some = [_region((10, 10, 30, 30), kind=k)
            for k in ("bubble", "sfx", "narration")]
    assert only_kinds(some, []) == some
    assert only_kinds(some, None) == some
