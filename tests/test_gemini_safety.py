"""Gemini's safety thresholds, and what a refusal should look like.

lee, with the Google page open: *"it says on this websiet that i can turn off
the safety filter ... can you do that"*.

Google documents four categories whose threshold you set per request on your
own key - harassment, hate speech, sexually explicit, dangerous content - and
`OFF` is one of the documented values. Ordinary published manga trips these
constantly: a fight scene reads as dangerous content, an insult as harassment,
and the whole page comes back with nothing in it.

What this does NOT do, and cannot at any threshold, is switch off Google's
built-in protections against core harms such as child safety. Those are not
configurable. A page can still be refused with the four turned down - which is
the other half of this file.

Two more things had to be right for it to be honest:

* **It only goes to Google.** The same field posted at OpenAI, Groq or a local
  llama.cpp is at best ignored and at worst a 400, so it is gated on the
  endpoint being Google's, and a 400 that names it drops it and retries rather
  than failing the page.
* **A refusal reads like a refusal.** Before this, a refused page came back
  with an empty message, failed the schema check, was retried twice, and
  reported something about missing regions - true, and no use to anybody.
"""
import json
import pytest

from mangatl import translate as T
from where import PKG


# ------------------------------------------------------------ the request

def test_the_four_categories_google_lets_you_set():
    assert T.GEMINI_HARMS == ("HARM_CATEGORY_HARASSMENT",
                              "HARM_CATEGORY_HATE_SPEECH",
                              "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                              "HARM_CATEGORY_DANGEROUS_CONTENT")


def test_the_body_is_the_shape_the_endpoint_documents():
    b = T.safety_body("OFF")
    assert list(b) == ["google"]
    ss = b["google"]["safety_settings"]
    assert len(ss) == 4
    assert all(set(x) == {"category", "threshold"} for x in ss)
    assert all(x["threshold"] == "OFF" for x in ss)
    assert T.safety_body("BLOCK_ONLY_HIGH")["google"]["safety_settings"][0][
        "threshold"] == "BLOCK_ONLY_HIGH"


def test_only_an_endpoint_that_has_the_switch_is_asked():
    g = "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert T.is_google_endpoint(g)
    assert not T.is_google_endpoint("https://api.openai.com/v1")
    assert not T.is_google_endpoint("http://localhost:11434/v1")
    assert not T.is_google_endpoint("")
    # ...and the client does not carry it where there is no such field, which
    # is ignored at best and a 400 at worst
    assert T.OpenAICompatClient(g, "m", "k", safety="OFF").safety == "OFF"
    assert T.OpenAICompatClient("https://api.openai.com/v1", "m", "k",
                                safety="OFF").safety == ""
    assert T.OpenAICompatClient(g, "m", "k").safety == ""


def _sent(monkeypatch, client, vision=False):
    """Run one request against a fake urlopen and return the body it posted."""
    seen = {}

    class Reply:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"choices": [
                {"message": {"content": "{}"}, "finish_reason": "stop"}]}
            ).encode()

    def fake_urlopen(req, timeout=None):
        seen["body"] = json.loads(req.data.decode())
        return Reply()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    if vision:
        client.complete_vision("sys", "user", "AAAA")
    else:
        client.complete("sys", "user")
    return seen["body"]


G = "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_it_reaches_the_wire_for_translation(monkeypatch):
    body = _sent(monkeypatch, T.OpenAICompatClient(G, "m", "k", safety="OFF"))
    ss = body["extra_body"]["google"]["safety_settings"]
    assert len(ss) == 4 and ss[0]["threshold"] == "OFF"


def test_it_reaches_the_wire_for_reading_the_page(monkeypatch):
    """The OCR turn is the one that matters most - it carries the artwork, and
    artwork is what trips these categories."""
    body = _sent(monkeypatch, T.OpenAICompatClient(G, "m", "k", safety="OFF"),
                 vision=True)
    assert body["extra_body"]["google"]["safety_settings"][0]["category"] \
        == "HARM_CATEGORY_HARASSMENT"


def test_nothing_extra_is_sent_when_it_is_off(monkeypatch):
    body = _sent(monkeypatch, T.OpenAICompatClient(G, "m", "k"))
    assert "extra_body" not in body, \
        "a project that has not asked for this must send exactly what it did before"


def test_an_endpoint_that_refuses_the_field_gets_the_page_anyway(monkeypatch):
    """A 400 naming the field is not a reason to fail somebody's page."""
    import urllib.error
    import urllib.request
    calls = []

    class Reply:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"choices": [
                {"message": {"content": "{}"}, "finish_reason": "stop"}]}
            ).encode()

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data.decode())
        calls.append(body)
        if "extra_body" in body:
            raise urllib.error.HTTPError(
                "u", 400, "Bad Request", {},
                __import__("io").BytesIO(
                    b'{"error":{"message":"Unknown name \\"extra_body\\""}}'))
        return Reply()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = T.OpenAICompatClient(G, "m", "k", safety="OFF")
    assert c.complete("sys", "user") == "{}"
    assert len(calls) == 2, calls
    assert "extra_body" in calls[0] and "extra_body" not in calls[1]
    # and it remembers, so the next page does not pay for the round trip again
    assert c._no_safety is True


# ------------------------------------------------------------ the refusal

def test_a_refused_page_says_so():
    why = T._refusal({"choices": [{"message": {"content": ""},
                                   "finish_reason": "content_filter"}]})
    assert why
    assert "refused" in why
    assert "cannot be switched off" in why, \
        "it has to say that turning the four down does not cover everything"


def test_a_block_reason_on_the_prompt_counts_too():
    why = T._refusal({"choices": [{"message": {"content": ""},
                                   "finish_reason": "stop"}],
                      "promptFeedback": {"blockReason": "SAFETY"}})
    assert why and "safety" in why.lower()


def test_a_real_answer_is_not_a_refusal():
    assert T._refusal({"choices": [{"message": {"content": "{\"a\":1}"},
                                    "finish_reason": "content_filter"}]}) == ""
    assert T._refusal({"choices": [{"message": {"content": "{}"},
                                    "finish_reason": "stop"}]}) == ""


def test_an_empty_answer_that_is_not_a_refusal_is_left_alone():
    """A model that simply ran out of tokens is a different problem and must
    not be reported as a refusal."""
    assert T._refusal({"choices": [{"message": {"content": ""},
                                    "finish_reason": "length"}]}) == ""
    assert T._refusal({}) == ""
    assert T._refusal({"choices": []}) == ""


def test_the_refusal_surfaces_instead_of_a_shape_error(monkeypatch):
    import urllib.request

    class Reply:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"choices": [
                {"message": {"content": ""},
                 "finish_reason": "content_filter"}]}).encode()

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: Reply())
    c = T.OpenAICompatClient(G, "m", "k")
    with pytest.raises(RuntimeError) as e:
        c.complete("sys", "user")
    assert "refused" in str(e.value)
    with pytest.raises(RuntimeError) as e2:
        c.complete_vision("sys", "user", "AAAA")
    assert "refused" in str(e2.value)


# ------------------------------------------------------------- the setting

def test_the_thresholds_are_set_on_every_project(tmp_path):
    """It was a switch, and everyone who found it turned it on: a chapter is
    refused on ordinary drawn violence often enough that no per-page answer
    works. lee: *"remove this no api shoud have a conetent filter"*."""
    import shutil
    from mangatl import editor
    from mangatl.project import Project
    root = str(tmp_path / "s")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    editor._ctx_from_settings(p)
    assert p.ctx.safety == "OFF"
    # ...and a project that saved the old switch OFF does not turn it back on
    p.settings["gemini_safety_off"] = False
    editor._ctx_from_settings(p)
    assert p.ctx.safety == "OFF"


def test_it_reaches_openrouter_whatever_the_model_string_says():
    """lee: *"all the trherolod for all the ais shiud bre off"*, then plainer:
    *"no ai shoud have any content filter is what i meant"*.

    Not a corner case: every step defaults to Gemini, and `or_openrouter`
    moves a step onto OpenRouter the moment the Google key is missing or
    refused. Gating on the URL alone put Google's filters back on for exactly
    the run that had already gone wrong once - and gating on a `google/` prefix
    still missed an alias, an `auto` route, or a Gemini reached under some
    other name. OpenRouter hands provider fields to the provider that knows
    them and drops the rest, so the block costs nothing on the routes that do
    not use it."""
    from mangatl.translate import OpenAICompatClient as C
    for m in ("google/gemini-3.5-flash", "anthropic/claude-sonnet-5",
              "openrouter/auto", ""):
        assert C("https://openrouter.ai/api/v1", m,
                 safety="OFF").safety == "OFF", m


def test_google_direct_still_takes_it():
    from mangatl.translate import OpenAICompatClient as C
    assert C("https://generativelanguage.googleapis.com/v1beta/openai/",
             "gemini-3.5-flash", safety="OFF").safety == "OFF"


def test_an_endpoint_with_no_such_field_is_sent_nothing_extra():
    """Not a filter left on: Claude and OpenAI publish no per-request
    threshold, so there is no off to send them. What would happen if one were
    posted anyway is the 400 further up this file."""
    from mangatl.translate import OpenAICompatClient as C
    assert C("https://api.openai.com/v1", "gpt-4o-mini",
             safety="OFF").safety == ""
    assert C("http://localhost:11434/v1", "qwen3", safety="OFF").safety == ""


def test_there_is_no_switch_left_to_find():
    root = PKG / "static"
    html = (root / "editor.html").read_text(encoding="utf8")
    js = (root / "js" / "project.js").read_text(encoding="utf8")
    assert 'id="gemini_safety_off"' not in html
    assert "gemini_safety_off" not in js


def test_what_it_still_cannot_do_is_written_down_where_it_is_set():
    """The switch carried that sentence on screen. With the switch gone it
    belongs next to the line that does the thing: Google's protections against
    core harms are not configurable at any threshold, and a page can still come
    back refused."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    at = src.index('p.ctx.safety = "OFF"')
    note = src[max(0, at - 1100):at]
    assert "not" in note and "configurable" in note
    assert "refused" in note


def test_the_makers_with_no_switch_are_named_rather_than_left_unsaid():
    """Otherwise the next reader of `takes_google_options` sees Claude and
    OpenAI missing from it and reads that as a filter somebody forgot to turn
    off. There is no field to send them; that is worth one sentence."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    at = src.index('p.ctx.safety = "OFF"')
    flat = " ".join(src[max(0, at - 1100):at].replace("#", " ").split())
    assert "Claude or OpenAI" in flat
    assert "per-request threshold" in flat
