"""The AI calls go through the project's relay; a person never holds a key.

lee: *"the user shoud not have eth keys"*. Until now the editor called Claude,
Gemini and OpenRouter with a key from a file the person had to make, and a
person with coins and no key was told "has no API key". Now a signed-in
editor with no key of its own points the same request at
`functions/relay.js`, with its Firebase ID token where the provider's key
would go; the relay checks the token and the coins, forwards the request
unchanged with the project's key, and hands the reply back.

The relay's decisions are pure JavaScript, run here under node without
Firebase. The editor's side is exercised with `account` stubbed: signed in
or not, a token or not.
"""
import json
import shutil
import subprocess

import pytest

from where import PKG
from mangatl import account, editor, translate
from mangatl.project import Project

FN = PKG / "firebase" / "functions"
INDEX = (FN / "index.js").read_text(encoding="utf-8")
RELAY = (FN / "relay.js").read_text(encoding="utf-8")
HTML = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
JS = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")


def _node(js):
    node = shutil.which("node")
    if not node:
        pytest.skip("no node")
    r = subprocess.run([node, "--input-type=module", "-e", js], cwd=str(FN),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ---------------------------------------------------------------- the relay

def test_the_relay_knows_three_providers_and_two_paths_each():
    got = _node("""
      import { relayTarget, PROVIDERS } from './relay.js';
      console.log(JSON.stringify({
        names: Object.keys(PROVIDERS).sort(),
        a: relayTarget('/relay/anthropic/v1/messages'),
        a2: relayTarget('/anthropic/messages'),
        g: relayTarget('/relay/gemini/chat/completions'),
        gm: relayTarget('/relay/gemini/v1/models'),
        o: relayTarget('/relay/openrouter/chat/completions'),
        bad: [relayTarget('/relay/openai/chat/completions'), relayTarget('/relay/gemini/embeddings'),
              relayTarget('/relay/anthropic/'), relayTarget(''), relayTarget('/relay/gemini/../../x')],
      }));""")
    assert got["names"] == ["anthropic", "clean", "gemini", "openrouter"]
    assert got["a"]["url"] == "https://api.anthropic.com/v1/messages"
    assert got["a2"] == got["a"], "the function's own name may lead the path or not"
    assert got["g"]["url"].startswith("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
    assert got["gm"]["path"] == "models"
    assert got["o"]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert got["bad"] == [None] * 5, "nothing off the short list is forwarded"


def test_the_token_is_read_from_where_each_client_puts_it():
    got = _node("""
      import { tokenOf, forwardHeaders } from './relay.js';
      console.log(JSON.stringify({
        bearer: tokenOf({ authorization: 'Bearer tok.one' }),
        anth: tokenOf({ 'x-api-key': 'tok.two' }),
        none: tokenOf({}),
        fa: forwardHeaders({ 'content-type': 'application/json', 'anthropic-version': '2023-06-01',
                             'x-api-key': 'tok', host: 'x', 'content-length': '9' }, 'anthropic', 'SECRET'),
        fg: forwardHeaders({ authorization: 'Bearer tok' }, 'gemini', 'GKEY'),
      }));""")
    assert got["bearer"] == "tok.one" and got["anth"] == "tok.two" and got["none"] == ""
    fa = got["fa"]
    assert fa["x-api-key"] == "SECRET", "the project's key, not the person's token"
    assert fa["anthropic-version"] == "2023-06-01"
    assert "host" not in fa and "content-length" not in fa
    assert got["fg"]["Authorization"] == "Bearer GKEY" and got["fg"]["content-type"] == "application/json"


def test_the_gate_is_an_account_with_coins():
    got = _node("""
      import { admit, usageOf, errorBody } from './relay.js';
      console.log(JSON.stringify({
        none: admit(null), broke: admit({ coins: 0 }), neg: admit({ coins: -3 }), ok: admit({ coins: 1 }),
        ua: usageOf({ usage: { input_tokens: 10, output_tokens: 5, cache_read_input_tokens: 7 } }),
        uo: usageOf({ usage: { prompt_tokens: 3, completion_tokens: 2, cost: 0.001,
                               prompt_tokens_details: { cached_tokens: 1 } } }),
        un: usageOf({}), e: errorBody('why', 'coins') }));""")
    assert got["none"]["status"] == 402 and not got["none"]["ok"]
    assert got["broke"]["status"] == 402 and got["neg"]["status"] == 402
    assert got["ok"]["ok"] is True
    assert got["ua"] == {"input": 10, "output": 5, "cached": 7, "cost": None}
    assert got["uo"] == {"input": 3, "output": 2, "cached": 1, "cost": 0.001}
    assert got["un"] is None
    assert got["e"] == {"error": {"message": "why", "type": "coins"}}, "the shape every provider's error has"


def test_the_function_holds_the_keys_as_secrets_and_verifies_the_token():
    body = INDEX[INDEX.index("export const relay = onRequest("):]
    body = body[:body.index("\n});") + 4]
    for must in ("secrets: [ANTHROPIC_KEY, GEMINI_KEY, OPENROUTER_KEY, CLEAN_TOKEN, CLEAN_URL]",
                 "verifyIdToken(token)", "admit(", "forwardHeaders(req.headers, to.backend, key)",
                 "timeoutSeconds: 540", "withBodyToken(body, to.backend, key)",
                 "Buffer.from(await up.arrayBuffer())"):
        assert must in body, must
    for name in ("ANTHROPIC_KEY", "GEMINI_KEY", "OPENROUTER_KEY", "CLEAN_TOKEN", "CLEAN_URL"):
        assert "defineSecret('%s')" % name in INDEX, name
    assert "console.log(JSON.stringify({ relay:" in body, "usage is logged"
    assert "req.rawBody" in body, "forwarded byte for byte"


def test_the_cleaner_is_the_fourth_and_its_token_rides_in_the_body():
    """lee: *"ther 4 key one for teh clner do tha too"*. Our own deploy reads
    `{token, model, image, mask}`; the relay puts OUR token in that field,
    whatever the editor sent (its ID token), and hands the PNG back."""
    got = _node("""
      import { relayTarget, withBodyToken, forwardHeaders } from './relay.js';
      console.log(JSON.stringify({
        t: relayTarget('/relay/clean'), t2: relayTarget('/clean'), bad: relayTarget('/relay/clean/x'),
        body: withBodyToken(JSON.stringify({ token: 'ID.TOKEN', model: 'anime-lama', image: 'AA', mask: 'BB' }), 'clean', 'SECRET'),
        left: withBodyToken('not json', 'clean', 'SECRET'),
        other: withBodyToken(JSON.stringify({ token: 'x' }), 'gemini', 'K'),
        h: forwardHeaders({ 'content-type': 'application/json', authorization: 'Bearer ID.TOKEN' }, 'clean', 'SECRET'),
      }));""")
    assert got["t"] == {"backend": "clean", "path": "", "url": None}, "the address is a secret, read at call time"
    assert got["t2"] == got["t"] and got["bad"] is None
    assert json.loads(got["body"]) == {"token": "SECRET", "model": "anime-lama", "image": "AA", "mask": "BB"}
    assert got["left"] == "not json"
    assert json.loads(got["other"]) == {"token": "x"}, "only the cleaner carries its key in the body"
    assert got["h"] == {"content-type": "application/json"}, "no auth header for our own deploy, and no token passed on"


def test_signed_in_the_cleaner_goes_through_the_relay_and_a_deploy_of_your_own_still_wins(signed, tmp_path, monkeypatch):
    p = _proj(tmp_path)
    p.settings.update(ai_clean="all", clean_url="", clean_token="")
    url, tok, relayed = editor.cleaner_endpoint(p)
    assert relayed and url.endswith("/relay/clean") and tok == "ID.TOKEN"
    assert editor.cleaner_endpoint(p, token=False) == (url, "", True), "a gate asks for no token"
    neural, whole = editor._make_cleaner(p)
    assert neural is not None and whole is True, "the AI cleaner is on with nothing typed"
    # a checkout with its own deploy: address in settings, token from the file
    monkeypatch.setattr(editor.userdata, "env_key", lambda s: "MINE" if s == "clean" else "")
    p.settings["clean_url"] = "https://mine.modal.run"
    assert editor.cleaner_endpoint(p) == ("https://mine.modal.run", "MINE", False)
    # ...or the address from the file too
    monkeypatch.setattr(editor.userdata, "load_env", lambda path="": {"MANGATL_CLEAN_URL": "https://env.modal.run"})
    assert editor.cleaner_endpoint(p)[0] == "https://env.modal.run"


def test_signed_out_and_no_deploy_the_cleaner_is_local_and_says_to_sign_in(tmp_path, monkeypatch):
    monkeypatch.setattr(account, "signed_in", lambda: False)
    monkeypatch.setenv("MANGATL_ENV", "/nonexistent/keys.env")
    monkeypatch.delenv("MANGATL_CLEAN_TOKEN", raising=False)
    p = _proj(tmp_path)
    p.settings.update(ai_clean="all", clean_url="", clean_token="")
    assert editor.cleaner_endpoint(p) == ("", "", False)
    assert editor._make_cleaner(p) == (None, False)
    assert not editor._hosted_cleaning(p)


# --------------------------------------------------------------- the editor

@pytest.fixture
def signed(monkeypatch):
    """The editor as a signed-in person with no key anywhere."""
    monkeypatch.setattr(account, "signed_in", lambda: True)
    monkeypatch.setattr(account, "token", lambda force=False: "ID.TOKEN")
    monkeypatch.setattr(account, "config", lambda: {"apiKey": "k", "projectId": "mangatctproject",
                                                    "region": "us-central1"})
    monkeypatch.setenv("MANGATL_ENV", "/nonexistent/keys.env")
    for n in ("MANGATL_ANTHROPIC_KEY", "MANGATL_GEMINI_KEY", "MANGATL_OPENROUTER_KEY",
              "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(n, raising=False)


def _proj(tmp_path):
    return Project(None, str(tmp_path / "out"))


def test_signed_in_and_keyless_the_step_runs_through_the_relay(signed, tmp_path):
    p = _proj(tmp_path)
    p.settings.update({"translate_backend": "gemini", "translate_model": "gemini-3.7-flash"})
    assert editor.needs_key(p, "translate") == "", "nothing to ask the person for"
    editor._ctx_from_settings(p, "translate")
    assert p.ctx.relayed is True
    assert p.ctx.base_url == "https://us-central1-mangatctproject.cloudfunctions.net/relay/gemini"
    assert p.ctx.api_key == "ID.TOKEN", "the token goes where the key would"
    assert p.ctx.model == "gemini-3.7-flash" and p.ctx.backend == "gemini"
    # Claude the same way, and the SDK is pointed at the relay
    p.settings.update({"proofread_backend": "anthropic", "proofread_model": "claude-sonnet-5"})
    editor._ctx_from_settings(p, "proofread")
    assert p.ctx.relayed and p.ctx.base_url.endswith("/relay/anthropic")
    pytest.importorskip("anthropic")
    cl, mdl, kind = translate.make_client("anthropic", p.ctx.base_url, p.ctx.model, p.ctx.api_key)
    assert kind == "anthropic" and str(cl.base_url).rstrip("/").endswith("/relay/anthropic")


def test_a_key_of_their_own_still_wins_and_a_local_model_is_left_alone(signed, tmp_path, monkeypatch):
    p = _proj(tmp_path)
    p.settings.update({"translate_backend": "gemini", "translate_model": "gemini-3.7-flash",
                       "key_gemini": "THEIRS"})
    editor._ctx_from_settings(p, "translate")
    assert p.ctx.relayed is False and p.ctx.api_key == "THEIRS" and p.ctx.base_url == ""
    p.settings.update({"translate_backend": "ollama", "translate_model": "qwen", "key_gemini": ""})
    editor._ctx_from_settings(p, "translate")
    assert p.ctx.relayed is False and p.ctx.base_url == ""
    assert editor.needs_key(p, "translate") == ""


def test_signed_out_and_keyless_is_the_one_case_that_still_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(account, "signed_in", lambda: False)
    monkeypatch.setenv("MANGATL_ENV", "/nonexistent/keys.env")
    for n in ("MANGATL_GEMINI_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
              "MANGATL_OPENROUTER_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(n, raising=False)
    p = _proj(tmp_path)
    p.settings.update({"translate_backend": "gemini", "translate_model": "gemini-3.7-flash"})
    why = editor.needs_key(p, "translate")
    assert "Sign in" in why and "TCT Coins" in why
    assert "API key" not in why and ".env" not in why, "a person is never sent to find a key"
    editor._ctx_from_settings(p, "translate")
    assert p.ctx.relayed is False and p.ctx.api_key == ""


def test_a_token_that_cannot_be_had_leaves_the_step_unrelayed(signed, tmp_path, monkeypatch):
    def boom(force=False):
        raise account.NotSignedIn()
    monkeypatch.setattr(account, "token", boom)
    p = _proj(tmp_path)
    p.settings.update({"translate_backend": "gemini", "translate_model": "gemini-3.7-flash"})
    editor._ctx_from_settings(p, "translate")
    assert p.ctx.relayed is False and p.ctx.base_url == ""


def test_the_relay_url_still_reads_as_the_provider_to_the_options_rules():
    """Gemini's safety settings and OpenRouter's usage accounting are keyed on
    the URL; behind the relay the URL names the provider, so both still go."""
    assert translate.is_google_endpoint("https://x.cloudfunctions.net/relay/gemini")
    assert translate.is_openrouter_endpoint("https://x.cloudfunctions.net/relay/openrouter")
    assert not translate.is_google_endpoint("https://x.cloudfunctions.net/relay/anthropic")
    assert translate.takes_google_options("https://x.cloudfunctions.net/relay/gemini")


# --------------------------------------------------------------- the screen

def test_nothing_on_the_screen_mentions_a_key():
    sec = HTML[HTML.index('data-sec="translation"'):]
    sec = sec[:sec.index("</section>")]
    import re
    shown = re.sub(r"<!--.*?-->", "", sec, flags=re.S)
    assert "envKeys" not in shown and ".env" not in shown
    assert "API key" not in shown and "api key" not in shown.lower()
    assert "renderEnvKeys" not in JS and "ENV_KEYS" not in JS and "Open the keys file" not in JS
