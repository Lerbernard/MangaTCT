"""Each AI step can run on its own model.

lee: *"i wan t a difent ai for vsion that reads teh text and a diffrent ai for
translation they need to understand jappenese chinesse and koren and be cheap
but good ... i wan to keep sonnet 5 for proofrreding"*.

Reading a page is a vision job on every page; translating is a language job on
every page; proofreading runs once at the end. Paying Sonnet rates for all three
is paying the expensive model to do the cheap work. So each step carries its own
model, and - because reading with Gemini and proofreading with Claude is the
whole point - its own backend, address and key.

There WAS a project-wide engine behind these three - a "Claude model" menu and
a "Translation engine" menu - and a step with nothing set fell through to it.
Both are gone. lee: *"remove teh recomened tab and the translation engine and
the coins shou look at what ai is in each of teh step to use to bill"*, and he
is right: two places to set one thing is two places for them to disagree, and
the coin price could only ever quote one of the two.

What is locked here now:

* a step with a model set uses it, and leaves the other steps alone
* a step with NOTHING set falls back to `STEP_DEFAULTS` - a default, the same
  for every project, not a setting that can drift out of step with the screen
* a project set up on the old engine has it carried onto its three steps, once,
  so nothing anybody configured is lost
* the three per-step keys never leave the machine through `summary()`

The last one matters most: `summary()` is what `/api/project` returns to the
browser, so a key that shows up there is a key on the wire.
"""
import shutil

from mangatl.editor import AI_STEPS, STEP_DEFAULTS, _ctx_from_settings
from mangatl.project import Project, migrate_engine
from scratch import scratch
from where import PKG

ROOT = scratch("_tmp_stepai")


def _proj():
    """A project with nothing configured. There is no project-wide engine to
    set any more - every step brings its own."""
    shutil.rmtree(ROOT, ignore_errors=True)
    return Project(None, ROOT)


OLD_FILE = {"backend": "gemini", "model": "gemini-2.5-flash",
            "base_url": "https://old.invalid/v1", "api_key": "house-key"}


def _old_proj(saved=None):
    """A project READ OFF DISK from before the per-step boxes existed: one
    engine, one model, one key, and nothing per step.

    Written to disk and loaded back rather than poked into `settings`, because
    the migration has to read the FILE: every step has a model in `settings`
    whether the file mentioned one or not, and a migration that looked there
    would never fire.
    """
    import json
    import os
    shutil.rmtree(ROOT, ignore_errors=True)
    p = Project(None, ROOT)
    with open(p.state_path, encoding="utf-8") as fh:
        d = json.load(fh)
    d["settings"] = dict(OLD_FILE, **(saved or {}))
    with open(p.state_path, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    q = Project(None, ROOT)
    assert os.path.isfile(q.state_path)
    return q


def _clean():
    shutil.rmtree(ROOT, ignore_errors=True)


def test_the_steps_are_the_ones_the_pipeline_runs():
    """Three steps call a model, and each has boxes of its own, because a
    service you cannot see is a price you cannot check.

    `find` was here for a while, when Find text had an AI option. lee:
    *"remoeve teh whole ai box deection and just keep what we have now"* - so
    there is no such pass and there are no boxes for it.
    `tests/test_the_ai_find_pass_is_gone.py` guards the removal; this list is
    what the SCREEN and the PRICING are built from, and a step in it with
    nothing behind it is three settings to get wrong.
    """
    assert AI_STEPS == ("ocr", "translate", "proofread")


def test_a_step_with_nothing_set_uses_its_own_default():
    """Not "the project's engine" - there is no such thing any more. A default
    is the same for every project, so it cannot drift out of step with what
    the screen shows, which is exactly how the two menus that used to sit
    above these boxes ended up being able to disagree with the price."""
    p = _proj()
    try:
        for step in AI_STEPS:
            _ctx_from_settings(p, step)
            back, model = STEP_DEFAULTS[step]
            assert (p.ctx.backend, p.ctx.model) == (back, model), step
    finally:
        _clean()


def test_the_defaults_are_a_cheap_reader_and_a_good_writer():
    """Reading a page is a vision job a cheap model does well; writing the
    English is where the money should go; checking it is a judgement call
    worth a good model once at the end. If the three were the same there would
    be no reason for there to be three boxes."""
    from mangatl import coins
    for step, (back, model) in STEP_DEFAULTS.items():
        assert coins.priced(model, back), step        # never the unknown rate
        # ...and it is a model the menu for that step really OFFERS. A default
        # that has fallen off the menu - retired, or displaced at its price by
        # a newer model, which is how Gemini 3.7 pushed 3.6 out - leaves the
        # settings screen showing a row nothing else on it agrees with.
        assert model in coins.offered(back, step), step
    assert coins.rate_for(STEP_DEFAULTS["ocr"][1]).inp < \
        coins.rate_for(STEP_DEFAULTS["proofread"][1]).inp


def test_the_defaults_are_written_down_in_exactly_one_place():
    """`Project.settings` is where they live and where the screen reads them.
    `editor.STEP_DEFAULTS` is the last resort for a project.json old enough to
    be missing the keys - and if the two disagree, a step falls back to a model
    the screen never showed and the price is for something else again. That is
    the whole failure these three boxes replaced."""
    p = _proj()
    try:
        for step, (back, model) in STEP_DEFAULTS.items():
            assert p.settings[f"{step}_model"] == model, step
            assert p.settings[f"{step}_backend"] == back, step
    finally:
        _clean()


def test_an_old_project_keeps_the_engine_it_was_set_up_with():
    """The screen that set it is gone. Copy it onto the three steps, once, so
    nobody opens the app to find their model, their address and their key have
    quietly become somebody else's defaults."""
    p = _old_proj()
    try:
        for step in AI_STEPS:
            _ctx_from_settings(p, step)
            assert p.ctx.model == "gemini-2.5-flash", step
            assert p.ctx.backend == "gemini", step
            assert p.ctx.base_url == "https://old.invalid/v1", step
            assert p.ctx.api_key == "house-key", step
    finally:
        _clean()


def test_the_migration_leaves_a_step_that_was_already_set_alone():
    """A project that DID use the per-step boxes must not have them
    overwritten by the old menu it also happens to carry."""
    p = _old_proj({"ocr_model": "gemini-3.5-flash-lite",
                   "ocr_backend": "gemini", "ocr_key": "reader-key"})
    try:
        _ctx_from_settings(p, "ocr")
        assert p.ctx.model == "gemini-3.5-flash-lite"
        assert p.ctx.api_key == "reader-key"
        _ctx_from_settings(p, "translate")
        assert p.ctx.model == "gemini-2.5-flash"
    finally:
        _clean()


def test_a_project_with_nothing_to_migrate_is_not_touched():
    """A new project has no old engine to carry, and its own defaults must
    survive the migration untouched."""
    p = _proj()
    try:
        assert migrate_engine(p.settings, {}) is False
        assert p.settings["ocr_model"] == "gemini-3.5-flash-lite"
        # ...and a file that names a step but no engine is not migrated either.
        assert migrate_engine(p.settings, {"ocr_model": "x"}) is False
    finally:
        _clean()


def test_each_step_picks_up_its_own_model():
    p = _proj()
    try:
        # A key for the step, because a step with no key it can use is not used
        # at all - reading and translating come pointed at Google by default
        # now, and an install with no Google key has to carry on working.
        p.settings.update({"ocr_key": "k", "translate_key": "k",
                           "proofread_key": "k"})
        p.settings["ocr_model"] = "gemini-2.5-flash-lite"
        p.settings["translate_model"] = "gemini-2.5-flash"
        p.settings["proofread_model"] = "claude-sonnet-5"
        _ctx_from_settings(p, "ocr")
        assert p.ctx.model == "gemini-2.5-flash-lite"
        _ctx_from_settings(p, "translate")
        assert p.ctx.model == "gemini-2.5-flash"
        _ctx_from_settings(p, "proofread")
        assert p.ctx.model == "claude-sonnet-5"
    finally:
        _clean()


def test_one_step_set_does_not_move_the_others():
    """Setting the reader must not drag the translator onto Gemini."""
    p = _proj()
    try:
        p.settings["ocr_model"] = "gemini-2.5-flash-lite"
        p.settings["ocr_backend"] = "gemini"
        _ctx_from_settings(p, "translate")
        assert (p.ctx.backend, p.ctx.model) == STEP_DEFAULTS["translate"]
    finally:
        _clean()


def test_a_step_can_live_on_another_provider_with_its_own_key():
    p = _proj()
    try:
        p.settings.update({"ocr_model": "gemini-2.5-flash-lite",
                           "ocr_backend": "gemini",
                           "ocr_base_url": "https://example.invalid/v1",
                           "ocr_key": "reader-key"})
        _ctx_from_settings(p, "ocr")
        assert p.ctx.backend == "gemini"
        assert p.ctx.base_url == "https://example.invalid/v1"
        assert p.ctx.api_key == "reader-key"
        # ...and the next step is on its own default, with no key of its own -
        # a step's key belongs to that step and is never lent to another.
        _ctx_from_settings(p, "translate")
        assert (p.ctx.backend, p.ctx.model) == STEP_DEFAULTS["translate"]
        assert p.ctx.api_key == ""
    finally:
        _clean()


def test_a_backend_without_a_model_gets_the_default_model():
    """A half-filled row must not post model="" to a provider. It used to fall
    all the way back to the project's engine, provider and all; now the row's
    own provider is kept - it is what somebody chose - and only the missing
    model comes from the default."""
    p = _proj()
    try:
        p.settings.update({"ocr_backend": "openai", "ocr_key": "reader-key",
                           "ocr_model": ""})
        _ctx_from_settings(p, "ocr")
        assert p.ctx.model == STEP_DEFAULTS["ocr"][1]
        assert p.ctx.model != ""
        assert p.ctx.backend == "openai"
        assert p.ctx.api_key == "reader-key"
    finally:
        _clean()


def test_blank_step_fields_mean_not_set_and_not_set_to_nothing():
    p = _proj()
    try:
        p.settings.update({"translate_model": "gemini-2.5-flash",
                           "translate_backend": "", "translate_base_url": "",
                           "translate_key": ""})
        _ctx_from_settings(p, "translate")
        assert p.ctx.model == "gemini-2.5-flash"
        assert p.ctx.backend == STEP_DEFAULTS["translate"][0]   # not blanked
    finally:
        _clean()


def test_whitespace_only_is_not_a_model():
    p = _proj()
    try:
        p.settings["ocr_model"] = "   "
        _ctx_from_settings(p, "ocr")
        assert p.ctx.model == STEP_DEFAULTS["ocr"][1]
    finally:
        _clean()


def test_an_unknown_step_name_changes_nothing():
    p = _proj()
    try:
        p.settings["ocr_model"] = "gemini-2.5-flash-lite"
        # A step that calls no model gets no step's engine - not the reader's,
        # and not a leftover from whichever step ran last.
        _ctx_from_settings(p, "clean")
        assert p.ctx.model != "gemini-2.5-flash-lite"
        assert p.ctx.api_key == ""
        _ctx_from_settings(p)
        assert p.ctx.model != "gemini-2.5-flash-lite"
    finally:
        _clean()


def test_the_step_keys_never_reach_the_browser():
    """`summary()` is the payload of /api/project. A key in there is a key on
    the wire."""
    p = _proj()
    try:
        for step in AI_STEPS:
            p.settings[f"{step}_key"] = f"secret-{step}"
        s = p.summary()["settings"]
        blob = repr(s)
        for step in AI_STEPS:
            assert s[f"{step}_key"] == "set"
            assert f"secret-{step}" not in blob
        assert "house-key" not in blob
    finally:
        _clean()


def test_unset_step_keys_report_as_empty_not_set():
    p = _proj()
    try:
        s = p.summary()["settings"]
        for step in AI_STEPS:
            assert s[f"{step}_key"] == ""
    finally:
        _clean()


def test_every_step_field_has_a_default():
    """A missing default means `.get()` returns None somewhere and the settings
    dialog writes `undefined` back.

    Two of them have a real default rather than a blank one: reading and
    translating come set up for Google AI Studio, which is what they are worth
    doing on. lee: *"these shoud be teh default"*. What matters here is that
    every field is PRESENT and is a string."""
    p = _proj()
    try:
        for step in AI_STEPS:
            for suffix in ("model", "backend", "base_url", "key"):
                v = p.settings[f"{step}_{suffix}"]
                assert isinstance(v, str), (step, suffix, v)
        # ...and nothing arrives with a key already in it
        for step in AI_STEPS:
            assert p.settings[f"{step}_key"] == ""
            assert p.settings[f"{step}_base_url"] == ""
        # Proofreading used to arrive BLANK, meaning "the project's engine".
        # There is no project engine any more, and blank would be a step the
        # price screen could not name - so it arrives named, on the model lee
        # picked for it: *"i wan to keep sonnet 5 for proofrreding"*.
        assert p.settings["proofread_model"] == "claude-sonnet-5"
        assert p.settings["proofread_backend"] == "anthropic"
    finally:
        _clean()


def test_the_pipeline_asks_for_the_right_step():
    """The three callers name their own step - a copy-paste that leaves
    do_translate asking for "ocr" would silently route translation through the
    reader's cheap model."""
    import inspect
    from mangatl import editor
    # Read text has two readers now, and only one of them has a context to
    # build - so for `ocr` the call sits in the AI arm, `_read_with_ai`,
    # rather than in `do_ocr` itself. The rule is unchanged: whoever builds a
    # context names the step it is for.
    for fn, step in ((editor._read_with_ai, "ocr"),
                     (editor.do_translate, "translate"),
                     (editor.do_proofread, "proofread")):
        src = inspect.getsource(fn)
        assert f'_ctx_from_settings(p, "{step}")' in src, fn.__name__
    # ...and the offline arm builds none at all.
    assert "_ctx_from_settings" not in inspect.getsource(editor._read_here)


def test_the_settings_api_masks_the_step_keys():
    """/api/settings echoes the saved sheet back; it must mask there too.

    This used to look for one literal line of source. The line was then
    refactored to go through `project.MASK` - the same constant the loader
    checks - and the test carried on passing against a string that no longer
    existed anywhere near the code it was about. Now it reads the loop, which
    is the thing that must be true: EVERY ai step, masked with the shared
    constant, and nothing left saying its own word for it.
    """
    import inspect
    import re

    from mangatl import editor as ed
    from mangatl import project as project_mod

    src = inspect.getsource(ed.Handler.do_POST)
    assert "for k in AI_STEPS:" in src, "the steps are not walked as a list"
    assert re.search(r'safe\[f"\{k\}_key"\] = \(project_mod\.MASK', src)
    # ...and the api key and the per-service keys, by the same constant.
    assert 'safe["api_key"] = project_mod.MASK' in src
    assert 'safe[f"key_{svc}"] = (project_mod.MASK' in src
    # A literal "set" next to a key would be a second place for the word.
    assert '_key"] = "set"' not in src
    assert project_mod.MASK == "set"


def test_the_dialog_offers_a_row_for_every_step():
    from pathlib import Path
    html = (PKG / "static"
            / "editor.html").read_text(encoding="utf8")
    for step in AI_STEPS:
        for suffix in ("model", "backend", "base_url"):
            assert f'id="{step}_{suffix}"' in html, f"{step}_{suffix}"


def test_no_key_is_typed_on_the_page_at_all_any_more():
    """It went from three boxes per step, to one per service, to none: lee:
    *"remove tehh keys they shoud happen in te backend"*.

    The rule the middle step existed for still holds underneath - a key is a
    fact about the PROVIDER, and `key_for` reads one per service, falling back
    to a per-step key only on the SAME service."""
    from mangatl.project import SERVICES
    html = (PKG / "static" / "editor.html").read_text(encoding="utf8")
    for svc in SERVICES:
        assert f'id="key_{svc}"' not in html, svc
    for step in AI_STEPS:
        assert f'id="{step}_key"' not in html, step
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def key_for("):]
    body = body[:body.index("\ndef ")]
    assert 'p.settings.get(f"key_{back}")' in body


# ------------------------------------------------- the model is a menu now

def test_the_models_offered_are_the_models_that_can_be_paid_for():
    """lee: *"inatd of habving to type teh names of teh model there shou dbe a
    drop downlist of all the models"*.

    Typing was how a chapter died halfway through with a 404 - providers
    retire models and nothing here would have told you - and it was also how a
    step ended up on a model the app cannot price, which silently charges the
    top rate. So the menu offers what can be paid for.
    """
    from mangatl import coins
    for back in ("anthropic", "gemini", "openrouter"):
        offered = coins.offered(back)
        assert offered, back
        for m in offered:
            assert coins.priced(m, back), (back, m)


def test_the_menu_opens_on_something_current():
    """In the price table's own order, which is newest first. Sorted by name it
    would open on the oldest model in the range, which is the one thing nobody
    wants and the one thing that gets picked by accident.

    Asked as "the newest one this app knows about" rather than by name: a
    named model is a line that has to be edited every time a provider ships,
    and it went red on 2026-09-03 for exactly that reason (Gemini 3.8 Flash
    arrived, so the top of the table is not 3.7 any more). What is worth
    holding is the ORDER, and the order is the table's.
    """
    from mangatl import coins
    for back in ("anthropic", "gemini"):
        first = coins.models_for(back)[0]
        newest = max(coins.models_for(back),
                     key=lambda m: (coins._version(m) or ("", -1, -1))[1:])
        assert (coins._version(first) or ("", -1, -1))[1:] == \
            (coins._version(newest) or ("", -1, -1))[1:], (back, first, newest)


def test_a_model_that_is_priced_but_retired_is_not_offered():
    """Somebody may still have one set - it stays PRICED, so they are not
    charged the unknown rate for it - but a menu of every model a provider
    ever shipped is a menu nobody can choose from."""
    from mangatl import coins
    for old in coins.RETIRED:
        assert coins.priced(old), old
        assert old not in coins.models_for("anthropic"), old
        assert old not in coins.models_for("gemini"), old


def test_a_provider_this_app_does_not_price_offers_nothing_of_its_own():
    """Ollama and the rest are asked what they have instead - their range is
    not in the table and it costs nothing to run either way.

    OpenRouter used to be one of these and is not any more: its ten slugs are
    priced, so it can be offered like the other two services rather than being
    a box you type a name into and hope."""
    from mangatl import coins
    for back in ("ollama", "openai", "groq", "cerebras", ""):
        assert coins.models_for(back) == [], back


def test_the_default_for_every_step_is_on_its_own_menu():
    """A step that opens on a model its own menu does not offer is a menu that
    changes the setting the moment somebody touches it."""
    from mangatl import coins
    p = _proj()
    try:
        for step, (back, model) in STEP_DEFAULTS.items():
            assert model in coins.offered(back, step), step
    finally:
        _clean()


# --------------------------------------------------------- the menu on screen

def _browser(fn, models=(), settings=None):
    """The settings screen, open on Translation engine."""
    import json
    import threading
    from http.server import ThreadingHTTPServer

    import browserpool
    import numpy as np
    import pytest as _pytest
    cv2 = _pytest.importorskip("cv2")
    from mangatl import editor

    shutil.rmtree(ROOT, ignore_errors=True)
    p = Project(None, ROOT)
    p.add_uploaded("001.png", cv2.imencode(
        ".png", np.full((400, 300, 3), 240, np.uint8))[1].tobytes())
    for step in AI_STEPS:
        p.settings[f"{step}_key"] = "k"
    p.settings.update(settings or {})
    p.save()
    was, editor.PROJECT = editor.PROJECT, p
    # The menu asks the PROVIDER what the key can reach, and these tests are
    # about the menu rather than about somebody's network. Answering nothing
    # is the honest stand-in: an empty crossing leaves the priced list
    # standing, which is what every assertion below is written against.
    from mangatl import translate as _t
    was_list, _t.list_models = _t.list_models, (lambda url, key="", **k: list(models))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1400, "height": 1000})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('settings'); setSettingsTab('translation')")
            browserpool.settled(pg)
            # Asked of what the SERVER returned, not of the rendered rows:
            # with a maker menu beside it the model select deliberately shows
            # one maker's models, so counting options is counting the filter.
            pg.wait_for_function(
                "($('ocr_model_sel')._all || []).length > 2", timeout=10000)
            try:
                return fn(pg, p)
            finally:
                assert not errs, errs
    finally:
        _t.list_models = was_list
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(ROOT, ignore_errors=True)


def test_the_model_is_a_menu_and_not_a_box_to_type_in():
    """lee: *"inatd of habving to type teh names of teh model there shou dbe a
    drop downlist of all the models"*."""
    from mangatl import coins

    def check(pg, p):
        for step in AI_STEPS:
            got = pg.evaluate(
                "[...document.querySelectorAll('#%s_model_sel option')]"
                ".map(o=>o.value)" % step)
            back = p.settings[f"{step}_backend"]
            assert got == coins.offered(back, step), step
            # It opens on what the step is really set to, not on the first row.
            assert pg.evaluate("$('%s_model_sel').value" % step) == \
                p.settings[f"{step}_model"], step
    _browser(check)


def test_choosing_from_the_menu_saves_it():
    def check(pg, p):
        pg.evaluate("""(()=>{ const s=$('translate_model_sel');
            s.value='gemini-2.5-flash-lite'; pickModel('translate'); })()""")
        pg.wait_for_function(
            "proj.settings.translate_model==='gemini-2.5-flash-lite'",
            timeout=8000)
        assert p.settings["translate_model"] == "gemini-2.5-flash-lite"
        assert pg.evaluate("$('translate_model').value") == \
            "gemini-2.5-flash-lite"
    _browser(check)


def test_there_is_no_way_back_to_typing_a_name():
    """lee: *"remove teh other from all the dropdowns"*.

    "Other…" was the way back to a text box, and typing a name is the thing
    the menu exists to stop: every id it could produce is either one the menu
    already offers, or one that cannot be run, cannot be priced, or both.
    """
    def check(pg, p):
        for step in AI_STEPS:
            vals = pg.evaluate(
                "[...document.querySelectorAll('#%s_model_sel option')]"
                ".map(o=>o.value+'|'+o.textContent)" % step)
            assert not any("__other__" in v or "Other" in v for v in vals), \
                (step, vals)
            # ...and the box behind the menu is a value, not something to type
            # into: no placeholder, nothing focusable, nothing to fill in.
            assert pg.evaluate("$('%s_model').type" % step) == "hidden", step
    _browser(check)


def test_a_menu_with_nothing_in_it_says_so():
    """A provider that answered with an empty list, or a key nobody has typed
    yet. An empty menu is something a person clicks at; a row that says why is
    the one place they are already looking."""
    def check(pg, p):
        # Nothing offered AND nothing already set - a step that HAS a model
        # keeps it on the menu, which is a different case and its own test.
        pg.evaluate("$('ocr_model').value=''; drawModels('ocr', [], null)")
        vals = pg.evaluate(
            "[...document.querySelectorAll('#ocr_model_sel option')]"
            ".map(o=>o.value+'|'+o.textContent)")
        assert any("check the key" in v for v in vals), vals
        # ...and picking it does not unset the step.
        was = p.settings["ocr_model"]
        pg.evaluate("$('ocr_model_sel').value=''; pickModel('ocr')")
        pg.wait_for_timeout(300)
        assert p.settings["ocr_model"] == was, "the empty row unset the step"
    _browser(check)


def test_a_model_that_is_set_but_not_on_the_menu_is_still_shown():
    """A local one, or an entry a provider has retired since. Taking somebody's
    setting away without asking is worse than an odd-looking menu."""
    def check(pg, p):
        pg.evaluate("""(()=>{ $('ocr_model').value='my-own-local-thing';
            drawModels('ocr', ['gemini-3.6-flash'], new Set(['gemini-3.6-flash']));
            })()""")
        got = pg.evaluate(
            "[...document.querySelectorAll('#ocr_model_sel option')]"
            ".map(o=>o.value)")
        assert "my-own-local-thing" in got, got
        assert pg.evaluate("$('ocr_model_sel').value") == "my-own-local-thing"
    _browser(check)


def test_a_model_the_app_cannot_price_says_so_on_the_menu():
    """Choosing one charges the top rate. That should be visible at the moment
    of choosing, not afterwards on the coin panel."""
    def check(pg, p):
        labels = pg.evaluate("""(()=>{
            drawModels('ocr', ['gemini-3.6-flash', 'mystery-9'],
                       new Set(['gemini-3.6-flash']));
            return [...document.querySelectorAll('#ocr_model_sel option')]
                     .map(o=>o.textContent); })()""")
        assert any("mystery-9" in t and "not priced" in t for t in labels), labels
        assert not any("gemini-3.6-flash" in t and "not priced" in t
                       for t in labels), labels
    _browser(check)


def test_changing_the_provider_asks_for_that_provider_s_models():
    """The model chosen for the old provider almost certainly does not exist
    on the new one, so the menu is refilled straight away rather than the next
    time somebody happens to look at it."""
    from mangatl import coins

    def check(pg, p):
        pg.evaluate("""(()=>{ $('ocr_backend').value='anthropic';
            saveSettings(); modelsStale('ocr'); })()""")
        pg.wait_for_function(
            "[...document.querySelectorAll('#ocr_model_sel option')]"
            ".some(o=>o.value.startsWith('claude-'))", timeout=10000)
        got = pg.evaluate(
            "[...document.querySelectorAll('#ocr_model_sel option')]"
            ".map(o=>o.value)")
        assert got == coins.offered("anthropic", "ocr"), got
        # ...and the Gemini model it was on is GONE, not kept as "as set". It
        # belongs to the provider that was just left and cannot run on this
        # one; the step moves to the first model the new provider offers, and
        # saves it, so the settings and the screen still agree.
        assert not any(m.startswith("gemini") for m in got), got
        pg.wait_for_function(
            "proj.settings.ocr_model==='%s'" % coins.offered("anthropic", "ocr")[0],
            timeout=8000)
        assert p.settings["ocr_model"] == coins.offered("anthropic", "ocr")[0]
    _browser(check)


def test_a_step_with_no_key_is_refused_before_the_run():
    """And by the ENDPOINT, not only by the function behind it - a run that
    starts and fails on page one has already taken the coins."""
    import json
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    import numpy as np
    import pytest as _pytest
    cv2 = _pytest.importorskip("cv2")
    from mangatl import editor

    shutil.rmtree(ROOT, ignore_errors=True)
    p = Project(None, ROOT)
    p.add_uploaded("001.png", cv2.imencode(
        ".png", np.full((400, 300, 3), 240, np.uint8))[1].tobytes())
    p.settings["translate_key"] = ""            # the one that matters
    p.save()
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        req = urllib.request.Request(
            base + "/api/translate_all", data=json.dumps({"pages": [0]}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=20)
            raise AssertionError("it started a run with no key")
        except urllib.error.HTTPError as e:
            assert e.code == 402
            body = e.read().decode()
            assert "Translate" in body and "TCT Coins" in body, body
        assert not p.job.get("running")
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(ROOT, ignore_errors=True)


# ------------------------------------------- the maker menu, in the browser

OR_MODELS = ["google/gemini-3.6-flash", "google/gemini-2.5-pro",
             "anthropic/claude-sonnet-5", "deepseek/deepseek-v3.2",
             "deepseek/deepseek-v4-flash"]

# Every step on OpenRouter and NO key for anything else - otherwise the rule
# under test kicks in and subtracts the lot: a Google key that can reach these
# models is a Google key that makes buying them through a reseller pointless,
# which is the whole point of `test_openrouter_drops_what_your_own_key_already
# _runs` and is not what these three are about.
_OR_ONLY = {"key_openrouter": "k", "key_gemini": "", "key_anthropic": "",
            "ocr_backend": "openrouter", "ocr_key": "",
            "translate_backend": "openrouter", "translate_key": "",
            "proofread_backend": "openrouter", "proofread_key": "",
            "translate_model": "google/gemini-3.6-flash",
            "ocr_model": "google/gemini-3.6-flash",
            "proofread_model": "anthropic/claude-sonnet-5"}


def test_a_reseller_gets_a_maker_menu_of_its_own():
    """The maker question is asked by the AI COMPANY menu now - lee:
    *"sinatsd of otrher it shodu be open deepsek quwen etc"* - so the maker
    select stays OFF screen (data-locked) but keeps carrying the filter: its
    options are still the makers, and the model menu is still one maker's
    models, not a hundred-model search."""
    def check(pg, p):
        pg.wait_for_function(
            "$('translate_vendor') && $('translate_vendor').options.length > 2",
            timeout=10000)
        assert pg.evaluate("$('translate_vendor').style.display") == "none"
        makers = pg.evaluate(
            "[...$('translate_vendor').options].map(o=>o.value)")
        assert makers == ["google", "anthropic", "deepseek", "*"], makers
        # ...and the model menu is only that maker's.
        shown = pg.evaluate(
            "[...$('translate_model_sel').options].map(o=>o.value)")
        assert all(m.startswith("google/") for m in shown), shown
    _browser(check, OR_MODELS, _OR_ONLY)


def test_choosing_a_maker_changes_the_models_and_saves_nothing():
    """Browsing the list must never change what the step runs on."""
    def check(pg, p):
        pg.wait_for_function(
            "$('translate_vendor') && $('translate_vendor').options.length > 2",
            timeout=10000)
        was = p.settings["translate_model"]
        pg.evaluate("$('translate_vendor').value='deepseek';"
                    "pickVendor('translate')")
        pg.wait_for_timeout(300)
        shown = pg.evaluate(
            "[...$('translate_model_sel').options].map(o=>o.value)")
        assert "deepseek/deepseek-v3.2" in shown, shown
        assert p.settings["translate_model"] == was, "browsing saved something"
        # ...and the model that IS set stays reachable even under another
        # maker's filter, because losing somebody's setting is worse.
        assert was in shown, shown
    _browser(check, OR_MODELS, _OR_ONLY)


def test_a_direct_service_has_no_maker_menu():
    """One maker. A menu with one row in it is a question with one answer."""
    def check(pg, p):
        for step in AI_STEPS:
            assert pg.evaluate("$('%s_vendor').style.display" % step) == "none", step
    _browser(check, ["gemini-3.6-flash", "gemini-2.5-pro",
                     "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"])
