"""The AI find pass is gone, and this file is what stops it coming back by
accident.

lee: *"remoeve teh whole ai box deection and just keep what we have now"*.

There were two AI passes at Find text, built and removed in that order. The
first showed the model a numbered page and let it judge boxes; lee watched it
and said *"nvm remove it its pretty bad remove the ai"*, and
`tests/test_ai_boxes.py` guards that one. The second, guarded here, was a
different design and worth saying what it was: it asked the model where the
writing was in overlapping tiles down a webtoon page, and then SNAPPED every
rectangle onto the ink underneath, so a loose answer could not put a box on the
artwork. It was off by default and it cost coins.

It is out anyway, because measurement got good enough that paying per page for
a second opinion stopped being worth the menu. What "what we have now" is, on
lee's chapter 1, measured:

    the double balloon comes apart          142 blocks scored, 13 of 13 lobes
    a sound-effect box covers the stroke    55 of 82 boxes widened
    a caption comes back as a caption       16 of 23, 0 balloons harmed
    the coverage pass takes a second        16 artwork boxes gone
      opinion from CRAFT
    balloons, captions and asides boxed     29 of 30 over eight pages

**What these tests are for.** None of it is forbidden forever - it is forbidden
SILENTLY. Wiring it back in means coming here and saying out loud that it is
being re-added.

**And a fifth was, on 2026-08-15, and lasted an afternoon.** lee asked for a
proofchecker at the end of Find text - *"it hsoud validate boxes and check
where anyboxes where missed and if the boxes is around teh sfx"* - and it was
built to the one shape the four removals leave standing: it judged, it flagged,
it never drew a rectangle, and a change needed the model's own confidence AND a
measurement that agreed. `test_a_run_of_find_text_is_not_priced` below was
amended to let it take a price, then amended back.

He ran it and said: *"remove teh ai it did no meniful upgrade"*. So that is
**five passes over boxes, five removals**, and the fifth one had every guard
the first four lacked. The honest reading is not that the design was wrong
again - it is that there is not enough left for a judge to find. What Find text
measures is already close enough that a second opinion, however careful, is not
worth a call per page.

`detect/craft.py` is deliberately NOT covered by any of this. It is a text
detector that runs offline on the machine with no key and no coins, it is not
"AI" in the sense lee is removing, and it is doing load-bearing work in the
measured pass.
"""
import ast
import inspect

import pytest

cv2 = pytest.importorskip("cv2")

from where import PKG

ROOT = PKG
GONE = ("aidetect", "detect_ai", "_detect_ai", "find_with", "finding_with_ai",
        "prepare_ai_find", "find_warning", "find_ai_error")


# ---------------------------------------------------------- the pass is gone

def test_find_text_has_one_way_of_getting_boxes():
    """`detect` chose between measuring and asking. It does not choose any
    more, and the source says so - a settings key nobody reads cannot bring
    the branch back, but a branch can."""
    from mangatl import project

    src = (inspect.getsource(project.Project.detect)
           + inspect.getsource(project.Project._detect_measured))
    low = src.lower()
    for word in GONE:
        assert word not in low, word


def test_the_project_has_no_ai_find_method():
    from mangatl import project

    assert not hasattr(project.Project, "_detect_ai")


def test_nothing_imports_the_removed_module():
    """Not just `detect` - nothing in the package. An import anywhere else is
    a second door into it."""
    hits = []
    for f in sorted(ROOT.rglob("*.py")):
        if f.name in ("aidetect.py", "test_the_ai_find_pass_is_gone.py"):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if "aidetect" in a.name:
                        hits.append(str(f))
            elif isinstance(node, ast.ImportFrom):
                if any("aidetect" in (a.name or "") for a in node.names) \
                        or "aidetect" in (node.module or ""):
                    hits.append(str(f))
    assert not hits, hits


def test_the_module_is_a_note_and_nothing_else():
    """Left on disk because nothing here can delete a file on lee's machine.
    It must not be able to DO anything if something imports it anyway."""
    src = (ROOT / "detect" / "aidetect.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    body = [n for n in tree.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    assert body == [], "aidetect.py has code in it again: %r" % (body,)


def test_the_editor_has_no_ai_find_helpers():
    from mangatl import editor

    for name in ("finding_with_ai", "prepare_ai_find", "find_warning"):
        assert not hasattr(editor, name), name


def test_find_is_not_a_step_that_calls_a_model():
    """`AI_STEPS` drives the per-step service menus, the key masking and the
    pricing. A step with no pass behind it is three settings to get wrong."""
    from mangatl import editor
    from mangatl import project

    assert "find" not in editor.AI_STEPS
    assert "find" not in project.AI_STEPS
    assert editor.AI_STEPS == project.AI_STEPS, \
        "the two lists have to stay the same list"
    assert "find" not in editor.STEP_DEFAULTS
    assert "find" not in editor.PAID_STEPS


def test_no_setting_for_it_is_handed_out():
    from mangatl.project import Project

    s = Project.__dict__.get("DEFAULTS")
    src = inspect.getsource(Project)
    for key in ("find_with", "find_model", "find_backend", "find_base_url",
                "find_key"):
        assert '"%s"' % key not in src, key


def test_the_settings_page_does_not_offer_it():
    html = (ROOT / "static" / "editor.html").read_text(encoding="utf-8")
    for el in ("find_with", "find_backend", "find_model", "find_base_url",
               "findai", "syncFindAi"):
        assert el not in html, el


def test_the_browser_does_not_send_it_either():
    """A saved sheet carrying `find_with` would put the setting back on disk
    even with no menu to set it from."""
    js = (ROOT / "static" / "js" / "project.js").read_text(encoding="utf-8")
    for el in ("find_with", "syncFindAi", "findai", "'find'"):
        assert el not in js, el


def test_a_run_of_find_text_is_not_priced():
    """It was a call per page and paid for up front. Measurement is free, and
    a Find text that can ask for coins is the pass coming back."""
    import re

    src = (ROOT / "editor.py").read_text(encoding="utf-8")
    i = src.index('if path == "/api/detect_all":')
    j = src.index("if path ==", i + 10)
    branch = src[i:j]
    for word in ("afford_run", "needs_key", "step="):
        assert word not in branch, "%s is back in Find text: %r" % (word, branch)
    m = re.search(r'/api/page/\(\\d\+\)/detect"', src)
    assert m, "the single-page route moved; this test needs re-pointing"


# ------------------------------------------- ...and what replaced it stayed

def test_the_measured_pass_is_still_all_there():
    """The point of removing it is that measurement got good enough. If these
    go, the trade that justified the removal is gone too."""
    from mangatl.detect import comictext as CT

    man = CT.TUNING["manhwa"]
    assert man["split_height"] == 1.1, "the double balloon split"
    assert man["sfx_grow"] == 0.40, "the box that covers the whole effect"
    assert man["craft_x"] and man["craft_y"], "the second detector"
    assert hasattr(CT, "_straight_edges"), "the caption rule"
    assert hasattr(CT, "_seen_by"), "the second opinion"


def test_the_other_ai_was_not_touched():
    """"Remove the ai" is a sentence that could be read far too widely by
    somebody tidying up later. The reader, the translator, the proofreader and
    the hosted cleaner were never part of this."""
    from mangatl import editor

    for step in ("ocr", "translate", "proofread"):
        assert step in editor.AI_STEPS, step
        assert step in editor.STEP_DEFAULTS, step
    for fn in ("do_ocr", "do_translate", "do_proofread"):
        assert hasattr(editor, fn), fn


def test_craft_is_not_swept_up_with_it():
    """It has no key, costs no coins and runs on the machine. It is a
    measurement, and it is doing real work in the pass that remains."""
    from mangatl.detect import craft as CR

    assert hasattr(CR, "pieces") and hasattr(CR, "merge_into")
    src = (ROOT / "detect" / "comictext.py").read_text(encoding="utf-8")
    assert "from . import craft as _craft" in src


# ------------------------------- the secret machinery the pass shared

# `tests/test_is_the_ai_really_finding_it.py` went with the pass, and it was
# the only file testing any of the below. None of it was ever about the AI
# find pass - it is how EVERY step's key is handled - so it is carried over
# here rather than deleted with the thing it happened to live next to.
#
# Left untested for one turn, six mutants survived: the mask could be saved as
# if it were a key, a real key could be dropped, the guard need never be
# called, and the secret list could go back to being written out by hand.


def test_the_mask_is_never_stored_as_a_key():
    """`MASK` is a REPORT that a key exists. It goes out to the browser in the
    same field the key lives in, and anything that hands a whole settings
    object back - a `.tct` import, a restored snapshot, a script - hands it
    straight back. Then the field that said "(saved)" IS saved: three
    characters, and refused by every provider.

    lee saw exactly that: *"the key it has ends set"*. It ended `set` because
    it WAS `set`.
    """
    from mangatl.project import MASK, drop_masked_secrets

    incoming = {"api_key": MASK, "key_gemini": MASK, "ocr_key": MASK}
    dropped = drop_masked_secrets(incoming)
    assert incoming == {}, incoming
    assert sorted(dropped) == ["api_key", "key_gemini", "ocr_key"]


def test_a_real_key_is_left_alone():
    """The other way round is worse: a guard that drops every key would empty
    the settings of somebody who just typed one in."""
    from mangatl.project import drop_masked_secrets

    incoming = {"api_key": "sk-a-real-one", "key_gemini": "  ", "ocr_key": ""}
    dropped = drop_masked_secrets(incoming)
    assert incoming["api_key"] == "sk-a-real-one"
    assert "api_key" not in dropped


def test_whitespace_round_the_mask_does_not_smuggle_it_through():
    from mangatl.project import MASK, drop_masked_secrets

    incoming = {"api_key": "  %s\n" % MASK}
    assert drop_masked_secrets(incoming) == ["api_key"]
    assert incoming == {}


def test_the_guard_is_actually_called_on_the_way_in():
    """A guard nobody calls is a comment."""
    import inspect

    from mangatl import editor

    src = inspect.getsource(editor.Handler.do_POST)
    assert "project_mod.drop_masked_secrets(new)" in src


def test_the_secret_list_is_built_and_not_written_out():
    """It has been wrong twice when written by hand: once a fourth AI step's
    key went to the browser in the clear, once the same key was left out of
    the strip-the-whitespace list on save. It is built from `AI_STEPS` and
    `SERVICES`, so adding a step cannot forget it."""
    import inspect

    from mangatl import project

    src = inspect.getsource(project.secret_keys)
    assert 'for k in AI_STEPS' in src
    assert 'for s in SERVICES' in src
    got = project.secret_keys()
    for step in project.AI_STEPS:
        assert f"{step}_key" in got, step
    for svc in project.SERVICES:
        assert f"key_{svc}" in got, svc
    assert "api_key" in got and "clean_token" in got


def test_removing_the_find_step_took_its_key_with_it():
    """The list is built, so this follows - but it is the whole reason the
    list is built, so it is worth one line."""
    from mangatl import project

    assert "find_key" not in project.secret_keys()


# ---------------------------------- ...and the refusal names the right step

def test_a_refusal_names_the_step_that_was_running():
    """The message said "the OCR step's key was refused" whatever had called,
    because `step_name` was only ever set by the AI find pass and every other
    step took the "OCR" fallback. Removing that pass left the fallback as the
    only path - so a refusal on Translate blamed the reader, and sent you to
    fix settings that were never the problem."""
    from mangatl.translate import make_client

    cl, _m, kind = make_client(backend="openai", base_url="http://x/v1",
                               model="m", api_key="k", step_name="Translate")
    assert kind == "openai"
    assert cl.step_name == "Translate"


def test_every_step_has_a_name_to_be_refused_under():
    from mangatl import editor

    for step in editor.AI_STEPS:
        assert editor.STEP_LABEL.get(step), step


def test_the_context_carries_it_to_the_client():
    import inspect

    from mangatl import editor
    from mangatl import translate

    assert 'p.ctx.step_name = STEP_LABEL.get(step, "")' in \
        inspect.getsource(editor._ctx_from_settings)
    src = inspect.getsource(translate)
    assert src.count('step_name=getattr(ctx, "step_name", "") or "")') == 3, \
        "one of the three places a client is built is not passing it"


def test_the_refusal_itself_says_which_step(monkeypatch):
    """Not just that the client carries the name - that the message uses it.
    Driven through `complete`, with the provider answering 400 and "invalid
    api key", because the name is read at the `raise` and a test that only
    checks the attribute passes with the raise hardcoded to "OCR"."""
    import io
    import urllib.error

    from mangatl import translate as T

    def refuse(req, timeout=None):
        raise urllib.error.HTTPError(
            "http://x/v1/chat/completions", 400, "Bad Request", {},
            io.BytesIO(b'{"error":{"message":"invalid api key"}}'))

    # `complete` imports urllib inside itself, so the module object is the
    # one to patch.
    import urllib.request as _ur
    monkeypatch.setattr(_ur, "urlopen", refuse)

    cl, _m, _k = T.make_client(backend="openai", base_url="http://x/v1",
                               model="m", api_key="sk-abcd",
                               step_name="Translate")
    with pytest.raises(RuntimeError) as e:
        cl.complete("sys", "user")
    msg = str(e.value)
    assert "Translate" in msg, msg
    assert "the OCR step" not in msg, msg
    assert "the translation step" not in msg, msg

    # ...and the OTHER request path. There are two, they had two different
    # hardcoded names, and a test that drove one of them left the other
    # naming the reader whatever was running.
    cl2, _m2, _k2 = T.make_client(backend="openai", base_url="http://x/v1",
                                  model="m", api_key="sk-abcd",
                                  step_name="Proofread")
    with pytest.raises(RuntimeError) as e2:
        cl2.complete_vision("sys", "user", "iVBORw0KGgo=")
    msg2 = str(e2.value)
    assert "Proofread" in msg2, msg2
    assert "the OCR step" not in msg2, msg2


# ---------------------------------------- what the step name nearly cost

def test_the_series_context_only_holds_declared_fields():
    """`Project._state` serialises `ctx.__dict__` whole, and `Project.load`
    reads it back with `SeriesContext(**saved)`. So setting an undeclared
    attribute on the context writes a key the constructor then refuses.

    That is what `p.ctx.step_name = ...` did. `load` raised, `_load_or_scan`
    swallowed it into a bare `except`, `rescan` found an empty input folder
    and SAVED an empty project over the chapter. One transient string, and
    every project saved afterwards would not open.
    """
    import dataclasses

    from mangatl.translate import SeriesContext

    assert "step_name" in {f.name for f in dataclasses.fields(SeriesContext)}


def test_a_context_key_this_version_does_not_know_costs_nothing():
    """The general form. A project.json from a different version must open,
    minus the key nobody recognises - a key is worth nothing and a chapter is
    worth everything."""
    import json
    import shutil

    import numpy as np

    from mangatl.project import Project
    from scratch import scratch

    root = scratch("_tmp_oldctx")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.add_uploaded("p0.png", cv2.imencode(
        ".png", np.full((40, 40, 3), 240, np.uint8))[1].tobytes())
    p.save()

    path = p.state_path
    d = json.load(open(path, encoding="utf-8"))
    d["context"]["something_from_the_future"] = "hello"
    json.dump(d, open(path, "w", encoding="utf-8"))

    again = Project(None, root)
    assert len(again.pages) == 1, "the page did not survive an unknown key"
    shutil.rmtree(root, ignore_errors=True)


def test_a_state_file_that_cannot_be_read_is_not_saved_over():
    """The last line of defence, and the one that turns a bug into a scare
    instead of a loss. If the file cannot be parsed at all, leave it alone:
    an empty rescan written over a chapter is unrecoverable, and a project
    that refuses to open is not."""
    import shutil

    from mangatl.project import Project
    from scratch import scratch

    root = scratch("_tmp_badstate")
    shutil.rmtree(root, ignore_errors=True)
    Project(None, root)
    with open(root + "/project.json", "w", encoding="utf-8") as fh:
        fh.write("{ this is not json")
    before = open(root + "/project.json", encoding="utf-8").read()
    again = Project(None, root)
    assert again.pages == []
    after = open(root + "/project.json", encoding="utf-8").read()
    assert after == before, "an unreadable project.json was overwritten"
    shutil.rmtree(root, ignore_errors=True)
