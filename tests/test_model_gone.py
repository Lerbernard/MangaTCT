"""A retired model says so in words, not in JSON.

lee, mid-chapter:

    RuntimeError: OCR server returned 404: [{ "error": { "code": 404,
    "message": "This model models/gemini-2.5-flash-lite is no longer available
    to new users. Please update your code to use a newer model for the latest
    features and i (translate.py:797 in complete_vision)

Everything in that line is true and none of it is usable. It does not say which
setting to change, it does not say what to change it to, and the one thing the
editor could find out for you — what this key CAN use — it never asks.

Providers retire models on their own schedule; this will happen again. So the
error names the model, names the setting, and lists what works.
"""
import json
import urllib.error

import pytest

from mangatl import translate
from scratch import scratch


GEMINI_404 = json.dumps({"error": {
    "code": 404,
    "message": ("This model models/gemini-2.5-flash-lite is no longer "
                "available to new users. Please update your code to use a "
                "newer model."),
    "status": "NOT_FOUND"}})


def _err(body=GEMINI_404, code=404):
    return translate._model_error("OCR", "gemini-2.5-flash-lite", code, body,
                                  "https://x/v1", "k")


@pytest.fixture
def no_network(monkeypatch):
    """Every test here decides for itself what the provider's list says."""
    monkeypatch.setattr(translate, "list_models",
                        lambda *a, **k: ["gemini-3.5-flash",
                                         "gemini-3.5-flash-lite",
                                         "text-embedding-004"])


def test_it_names_the_model_that_is_gone(no_network):
    msg = _err()
    assert "gemini-2.5-flash-lite" in msg
    # and what the provider actually answered — a 403 is a key that is not
    # allowed this model, a 404 is a model that is not there, and the two are
    # fixed differently.
    assert "404" in msg, msg


def test_it_says_where_to_change_it(no_network):
    msg = _err()
    assert "Settings" in msg and "Translation engine" in msg


def test_it_lists_what_the_key_can_use(no_network):
    msg = _err()
    assert "gemini-3.5-flash-lite" in msg


def test_it_leaves_out_the_ones_that_cannot_write(no_network):
    """An embedding model is in the list and can never answer a chat request.
    Offering it is offering the next 404."""
    assert "embedding" not in _err()


def test_a_provider_that_will_not_list_still_gets_a_readable_error(monkeypatch):
    """No list is a worse message, not a broken one — and certainly not a
    second exception on top of the first."""
    monkeypatch.setattr(translate, "list_models", lambda *a, **k: [])
    msg = _err()
    assert "gemini-2.5-flash-lite" in msg
    assert "Settings" in msg


def test_a_long_list_is_cut_and_says_so(no_network):
    names = [f"m{k}" for k in range(30)]
    old, translate.list_models = translate.list_models, lambda *a, **k: names
    try:
        msg = translate._model_error("OCR", "old", 404, GEMINI_404,
                                     "https://x/v1", "k")
    finally:
        translate.list_models = old
    assert "and 22 more" in msg, msg
    assert msg.count(",") <= 8, msg


def test_an_unrelated_failure_is_reported_as_it_was():
    """A 500, a bad key, a rate limit — none of those are the model's name, and
    rewriting them into 'no such model' would send you to change the one
    setting that was right."""
    msg = translate._model_error("OCR", "m", 500, "upstream exploded",
                                 "https://x/v1", "k")
    assert msg == "OCR server returned 500: upstream exploded"


def test_a_401_is_not_turned_into_a_model_problem():
    msg = translate._model_error("OCR", "m", 401,
                                 '{"error":"invalid api key"}',
                                 "https://x/v1", "k")
    assert "401" in msg and "no such model" not in msg


def test_the_step_is_named(no_network):
    """Three steps can be on three different models. 'It broke' is not enough
    to know which of the three boxes to look in."""
    assert "OCR" in _err()
    assert "translation" in translate._model_error(
        "translation", "m", 404, GEMINI_404, "https://x/v1", "k")


# ------------------------------------------------------ asking the provider

class _Fake:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_the_list_comes_from_the_provider(monkeypatch):
    seen = {}

    def fake_open(req, timeout=0):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        return _Fake({"data": [{"id": "models/gemini-3.5-flash"},
                               {"id": "models/gemini-2.5-flash"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    got = translate.list_models("https://x/v1/", "secret")
    assert got == ["gemini-2.5-flash", "gemini-3.5-flash"]
    assert seen["url"] == "https://x/v1/models"
    assert seen["auth"] == "Bearer secret"


def test_a_provider_that_refuses_the_list_is_not_an_error(monkeypatch):
    """Ollama, an old llama.cpp, a proxy that only proxies /chat/completions.
    None of them should stop you typing a name in by hand."""
    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 404, "no", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert translate.list_models("https://x/v1", "k") == []


def test_the_names_are_the_short_ones():
    """Gemini answers `models/gemini-3.5-flash`. The chat endpoint takes
    either, but only one of the two is what a person recognises — and only one
    matches what they would have typed."""
    import urllib.request
    payload = _Fake({"data": [{"id": "models/gemini-3.5-flash"}]})
    old = urllib.request.urlopen
    urllib.request.urlopen = lambda req, timeout=0: payload
    try:
        assert translate.list_models("https://x/v1", "") == ["gemini-3.5-flash"]
    finally:
        urllib.request.urlopen = old


def test_only_a_leading_models_prefix_comes_off_the_name():
    """Cutting at the LAST slash is what broke OpenRouter.

    Gemini answers `models/gemini-3.5-flash` and the short form is what a
    person recognises. But OpenRouter names a model by who MAKES it, and
    `str(name).split("/")[-1]` turned `anthropic/claude-sonnet-5` into
    `claude-sonnet-5` — a name OpenRouter has never heard of, offered in a
    menu, chosen, and 404 one call later.
    """
    import urllib.request
    payload = _Fake({"data": [{"id": "models/gemini-3.5-flash"},
                              {"id": "anthropic/claude-sonnet-5"},
                              {"id": "google/gemini-2.5-flash-lite"}]})
    old_open = urllib.request.urlopen
    urllib.request.urlopen = lambda req, timeout=0: payload
    try:
        assert translate.list_models("https://x/v1", "") == [
            "anthropic/claude-sonnet-5", "gemini-3.5-flash",
            "google/gemini-2.5-flash-lite"]
    finally:
        urllib.request.urlopen = old_open


def test_the_default_gemini_model_is_one_new_keys_can_use():
    """The preset is what a project gets with nothing typed in. Pointing it at
    a model Google has closed to new keys means the app fails on first use for
    exactly the people who have never used it before."""
    assert translate.LOCAL_PRESETS["gemini"]["model"] == "gemini-3.5-flash"


# ------------------------------------------------------ the suggestion list

def _serve(fn, root=scratch("_tmp_models")):
    import shutil, threading
    from http.server import ThreadingHTTPServer
    import urllib.request
    import numpy as np
    cv2 = pytest.importorskip("cv2")
    from mangatl import editor
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.add_uploaded("a.png", cv2.imencode(
        ".png", np.full((60, 40, 3), 240, np.uint8))[1].tobytes())
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def post(path, obj):
        req = urllib.request.Request(
            base + path, data=json.dumps(obj).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    try:
        return fn(p, post)
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def test_a_priced_provider_answers_from_the_price_table(monkeypatch):
    """The model box offers what works instead of waiting for you to guess
    wrong — and for a provider whose range this app PRICES, what works means
    what can be paid for. An entry nobody priced would put the step on the top
    rate the moment it was chosen, and the person choosing it would have no way
    to know.

    It also means the menu is there before a key is: no request, no round trip,
    and a list on a fresh install with nothing set up yet.
    """
    from mangatl import coins
    from mangatl import translate as t
    asked = []
    monkeypatch.setattr(t, "list_models",
                        lambda url, key, **k: asked.append(url) or ["asked"])

    def check(p, post):
        p.settings.update({"ocr_backend": "gemini", "ocr_key": ""})
        j = post("/api/models", {"step": "ocr"})
        assert j["models"] == coins.models_for("gemini")
        assert j["priced"] == j["models"]        # every one of them
        assert asked == [], "it went to the provider for a list it already had"
    _serve(check)


def test_a_provider_this_app_does_not_price_is_asked_what_it_has(monkeypatch):
    """Ollama, OpenRouter, anything local or odd. Their range is not in the
    price table — and it costs nothing to run either way — so the only honest
    list is the one the provider itself gives."""
    from mangatl import translate as t
    monkeypatch.setattr(t, "list_models",
                        lambda url, key, **k: [f"from:{url}", f"key:{key}"])

    def check(p, post):
        p.settings.update({"ocr_backend": "ollama", "ocr_key": "KEY"})
        got = post("/api/models", {"step": "ocr"})["models"]
        assert any(m.startswith("from:http://localhost:11434") for m in got), got
        assert "key:KEY" in got, got
    _serve(check)


def test_a_step_with_no_model_yet_still_gets_a_list(monkeypatch):
    """The first thing you do is open an EMPTY menu. A list that only appears
    once you have already chosen a working name is no help at all."""
    from mangatl import coins
    from mangatl import translate as t
    monkeypatch.setattr(t, "list_models", lambda url, key, **k: ["ok"])

    def check(p, post):
        p.settings.update({"ocr_backend": "gemini", "ocr_model": ""})
        assert post("/api/models", {"step": "ocr"})["models"] == \
            coins.models_for("gemini")
        # ...and a provider whose range is not in the price table is asked
        # what it has. It needs a key to ask with — all three services refuse
        # `GET /models` without one, so nothing is requested when there is
        # none.
        p.settings.update({"ocr_backend": "ollama", "ocr_model": "",
                           "ocr_key": "KEY"})
        assert post("/api/models", {"step": "ocr"})["models"] == ["ok"]
    _serve(check)


def test_claude_answers_from_the_written_list():
    """The Anthropic key the app uses has no /models to ask."""
    def check(p, post):
        p.settings.update({"ocr_backend": "anthropic"})
        got = post("/api/models", {"step": "ocr"})["models"]
        assert "claude-sonnet-5" in got, got
    _serve(check)


def test_asking_does_not_change_what_the_project_runs_on():
    """It is a question, not a setting. Leaving the context pointed at the
    step's provider would silently move the NEXT action onto it."""
    def check(p, post):
        p.settings.update({"backend": "anthropic", "model": "claude-sonnet-5",
                           "ocr_backend": "gemini", "ocr_model": "g",
                           "ocr_key": "KEY"})
        post("/api/models", {"step": "ocr"})
        assert p.ctx.backend != "gemini", p.ctx.backend
        assert p.ctx.api_key != "KEY"
    _serve(check)


def test_the_list_is_not_sent_until_the_project_has_its_own_back(monkeypatch):
    """The one above only sees the end of it, and for a while that was a
    coin-toss: the reply used to be written from inside the borrow and the
    context handed back after, so a run under load would sometimes read the
    list, act on it, and be answered by the step's provider. What matters is
    the ORDER — at the moment the answer goes out, the project is already
    back on its own model. Caught at the write, not after it."""
    from mangatl import editor
    seen = {}
    real = editor.Handler._json

    def spy(self, obj, code=200):
        if isinstance(obj, dict) and "models" in obj:
            seen["backend"] = editor.PROJECT.ctx.backend
            seen["key"] = editor.PROJECT.ctx.api_key
        return real(self, obj, code)

    monkeypatch.setattr(editor.Handler, "_json", spy)

    def check(p, post):
        # The other way round from the test above, so the borrow can be
        # answered from the written list and nothing goes near the network.
        p.settings.update({"backend": "gemini", "model": "g",
                           "key": "PROJECT", "ocr_backend": "anthropic",
                           "ocr_key": "OCR"})
        p.ctx.backend, p.ctx.api_key = "gemini", "PROJECT"
        got = post("/api/models", {"step": "ocr"})
        assert got["models"], got          # it still answers the question
        assert seen, "the answer never went through _json"
        assert seen["backend"] == "gemini", seen
        assert seen["key"] == "PROJECT", seen
    _serve(check)


# ------------------------------------------------ a key that was refused

BAD_KEY = json.dumps({"error": {
    "code": 400, "message": "Please pass a valid API key",
    "status": "INVALID_ARGUMENT"}})


def test_a_refused_key_is_not_reported_as_a_missing_model(no_network):
    """lee: *"RuntimeError: OCR server returned 400: ... Please pass a valid
    API key"*, with the key filled in and the model name right.

    Sending somebody to change the model when the model is right is the worst
    of the three answers — they change a setting that was correct and the next
    run fails the same way."""
    msg = translate._model_error("OCR", "gemini-3.5-flash-lite", 400, BAD_KEY,
                                 "https://x/v1", "abcdefghij1234")
    assert "key" in msg.lower(), msg
    assert "gemini-3.5-flash-lite" not in msg, msg
    assert "Settings" in msg


def test_it_says_which_key_it_had(no_network):
    """"Your key was refused" and "you have no key" are two different problems
    with two different fixes, and the message has to tell them apart."""
    got = translate._model_error("OCR", "m", 400, BAD_KEY, "https://x/v1",
                                 "sk-livekey-9876")
    assert "9876" in got, got
    assert "no key is set" not in got
    none = translate._model_error("OCR", "m", 400, BAD_KEY, "https://x/v1", "")
    assert "no key is set" in none, none


def test_it_warns_about_the_way_it_usually_happens(no_network):
    """A key copied out of a file comes with a newline on it, and fails exactly
    as a wrong key does."""
    msg = translate._model_error("OCR", "m", 401, '{"error":"unauthorized"}',
                                 "https://x/v1", "k")
    assert "newline" in msg or "space" in msg, msg


def test_a_missing_model_is_still_a_missing_model(no_network):
    """The two must not swap places."""
    msg = translate._model_error("OCR", "old-model", 404, GEMINI_404,
                                 "https://x/v1", "k")
    assert "old-model" in msg
    assert "was refused" not in msg


@pytest.mark.parametrize("given", [
    "  AIzaPASTED  ",              # a stray space either side
    "AIzaPASTED\n",                # copied out of a file
    '"AIzaPASTED"',                # copied with the quotes round the literal
    "'AIzaPASTED'\n",
])
def test_a_key_is_stored_the_way_it_was_meant(given):
    """Pasted keys arrive with whatever the copy picked up. The provider
    compares the string exactly, so a trailing newline is a 400 that reads as
    "but it's the same key"."""
    def check(p, post):
        post("/api/settings", {"settings": {"ocr_key": given,
                                            "translate_key": given,
                                            "proofread_key": given,
                                            "api_key": given}})
        for k in ("ocr_key", "translate_key", "proofread_key", "api_key"):
            assert p.settings[k] == "AIzaPASTED", (k, repr(p.settings[k]))
    _serve(check)


# --------------------------------------------- a step needs a key to be used

def test_the_reading_step_comes_set_up_for_google():
    """lee: *"these shoud be teh default"*, of Google AI Studio with
    gemini-3.5-flash-lite reading and gemini-3.6-flash translating."""
    import shutil as _sh
    from mangatl.project import Project
    root = scratch("_tmp_defaults")
    _sh.rmtree(root, ignore_errors=True)
    try:
        p = Project(None, root)
        assert p.settings["ocr_backend"] == "gemini"
        assert p.settings["ocr_model"] == "gemini-3.5-flash-lite"
        assert p.settings["translate_backend"] == "gemini"
        assert p.settings["translate_model"] == "gemini-3.6-flash"
    finally:
        _sh.rmtree(root, ignore_errors=True)


def test_a_step_with_no_key_says_so_before_the_chapter_starts():
    """It used to fall back to a project-wide engine, so a missing key was
    invisible and the run quietly happened somewhere else — on a model the
    screen did not name and the price was not quoted for.

    There is no project-wide engine any more. A step with no key is a step
    that cannot run, which is better, as long as it says so BEFORE the chapter
    starts rather than failing on page one with a provider's own wording about
    an invalid key.
    """
    from mangatl import editor

    def check(p, post):
        p.settings.update({"ocr_backend": "gemini",
                           "ocr_model": "gemini-3.5-flash-lite",
                           "ocr_key": ""})
        editor._ctx_from_settings(p, "ocr")
        assert p.ctx.backend == "gemini"          # what the screen says
        assert p.ctx.model == "gemini-3.5-flash-lite"
        why = editor.needs_key(p, "ocr")
        assert "Read text" in why and "API key" in why, why
        # ...and the step that DOES have one is not complained about.
        p.settings["translate_key"] = "AIza-yes"
        assert editor.needs_key(p, "translate") == ""
    _serve(check)


def test_a_step_you_run_yourself_needs_no_key():
    """Ollama and the rest answer without one, so asking would turn a working
    setup off."""
    from mangatl import editor

    def check(p, post):
        p.settings.update({"ocr_backend": "ollama", "ocr_model": "qwen2.5",
                           "ocr_key": ""})
        assert editor.needs_key(p, "ocr") == ""
    _serve(check)


def test_the_free_steps_are_never_asked_for_a_key():
    from mangatl import editor

    def check(p, post):
        for step in ("", "typeset", "export", "clean"):
            assert editor.needs_key(p, step) == "", step
    _serve(check)


def test_a_step_with_a_key_is_used():
    from mangatl import editor

    def check(p, post):
        p.settings.update({"backend": "anthropic", "api_key": "sk-project",
                           "ocr_backend": "gemini",
                           "ocr_model": "gemini-3.5-flash-lite",
                           "ocr_key": "AIzaMINE"})
        editor._ctx_from_settings(p, "ocr")
        assert p.ctx.backend == "gemini"
        assert p.ctx.model == "gemini-3.5-flash-lite"
        assert p.ctx.api_key == "AIzaMINE"
    _serve(check)


def test_a_local_step_needs_no_key_at_all():
    """Ollama and the rest answer without one, so asking for a key there would
    turn a working setup off."""
    from mangatl import editor

    def check(p, post):
        p.settings.update({"ocr_backend": "ollama", "ocr_model": "qwen2.5",
                           "ocr_key": ""})
        editor._ctx_from_settings(p, "ocr")
        assert p.ctx.backend == "ollama"
        assert p.ctx.model == "qwen2.5"
    _serve(check)


def test_a_key_belongs_to_its_step_and_is_never_lent_to_another():
    """A step used to be able to borrow the project's key when it was on the
    same provider. There is no project key any more, and borrowing between
    steps would be worse than the thing it replaced: the reader and the
    translator can be on the same provider with two different keys on purpose
    — a free tier for the cheap step and a paid one for the expensive step is
    exactly what somebody would set up."""
    from mangatl import editor

    def check(p, post):
        p.settings.update({"ocr_backend": "gemini", "ocr_key": "AIza-READER",
                           "ocr_model": "gemini-3.5-flash-lite",
                           "translate_backend": "gemini",
                           "translate_key": "AIza-WRITER",
                           "translate_model": "gemini-3.6-flash"})
        editor._ctx_from_settings(p, "ocr")
        assert p.ctx.api_key == "AIza-READER"
        editor._ctx_from_settings(p, "translate")
        assert p.ctx.api_key == "AIza-WRITER"
    _serve(check)


# ------------------------------------------- a line break that arrived twice

def test_a_double_escaped_break_becomes_a_line_break():
    """Some models escape the newline twice on the way out, so the JSON carries
    `"A\\\\nB"` and the region ends up holding a backslash and an n where the
    break should be.

    Caught in a real 23-page chapter of lee's: three pages had it and the other
    twenty did not, which is the worst kind of defect to spot by eye.
    """
    from mangatl.translate import _unescape_breaks as u
    assert u("『最初の聖女\\n生誕の地』") == "『最初の聖女\n生誕の地』"
    assert u("A\\r\\nB") == "A\nB"
    assert u("A\\rB") == "A\nB"


def test_a_real_break_is_left_alone():
    from mangatl.translate import _unescape_breaks as u
    assert u("A\nB") == "A\nB"
    assert u("plain") == "plain"
    assert u("") == ""


def test_the_reader_hands_back_real_breaks(monkeypatch):
    """Through `read_page_ocr`, not just the helper — the point is that nothing
    downstream ever sees the two characters."""
    from mangatl import translate as t
    from mangatl.models import Page, TextRegion

    r = TextRegion(id=1, bbox=(0, 0, 10, 10), kind="bubble")
    page = Page(image=None, regions=[r])

    class Fake(t.OpenAICompatClient):
        def complete_vision(self, *a, **k):
            return '{"regions":[{"id":1,"text":"上の行\\\\n下の行"}]}'

    monkeypatch.setattr(
        t, "make_client",
        lambda **k: (Fake("http://x/v1", "m", "k"), "m", "openai"))
    got = t.read_page_ocr(page, t.SeriesContext(), b"x")
    assert got[1] == "上の行\n下の行", repr(got[1])
