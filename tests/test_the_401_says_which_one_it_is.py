"""A refused cleaner token has two causes, and the bar named neither.

lee, seven identical lines in his console and one sentence on the screen::

    AI cleaning did not run - the cleaner refused the token (401).
    2 spots were filled in with the plain local method instead.
    mangatl: the cleaner refused the token (401) -- not asking again this run.
    https://leemarvinbernard--mangatl-clean-lama-cleaner-clean.modal.run

A 401 from the hosted cleaner is one of exactly two things:

  * the string in Settings is not the string in the deploy file - the wrong
    token is pasted; or
  * they are the SAME string and the deployed image was built from an older
    copy of that file, so it is still checking the token it was built with.
    Re-pasting the token can never fix this one, and it is the one people try.

`clean_check` already tells them apart. It just has to be ASKED - Settings ▸
Page cleaning ▸ Test cleaner - and nothing on the screen said so, which on a
run of seven pages is seven identical lines and no next step.

Nothing here needs the network. The token is a string in a file on this
machine and a string in the settings; hashing both answers it. And nothing
reads either one out loud - only whether two hashes agree.
"""
import hashlib

import pytest

from mangatl import editor as ED


class _P:
    def __init__(self, **s):
        self.settings = s


DEPLOY = "python -m modal deploy"


@pytest.fixture(autouse=True)
def quiet():
    """`clean_warning` reads module state; leave it as it was found."""
    was = dict(ED._AI_CLEAN_FAIL)
    yield
    ED._AI_CLEAN_FAIL.clear()
    ED._AI_CLEAN_FAIL.update(was)


def _refused(n=2, msg="the cleaner refused the token (401)"):
    ED._AI_CLEAN_FAIL.update(n=n, msg=msg, url="", used=0, cached=0,
                             refused="")


def _files(monkeypatch, entries):
    monkeypatch.setattr(ED, "_deploy_files", lambda: [dict(e) for e in entries])


def _sha(tok):
    return hashlib.sha1(tok.encode("utf-8")).hexdigest()


# ------------------------------------------------------- the two causes

def test_a_token_that_does_not_match_the_file_says_so(monkeypatch):
    _refused()
    _files(monkeypatch, [{"file": "lama_clean_modal.py",
                          "app": "mangatl-clean-lama",
                          "sha": _sha("the-real-one")}])
    p = _P(clean_token="something-else",
           clean_url="https://x--mangatl-clean-lama-cleaner-clean.modal.run")
    msg = ED.clean_warning(p)
    assert "does NOT match" in msg, msg
    assert "lama_clean_modal.py" in msg
    assert DEPLOY not in msg, "re-deploying is not the fix for this one"


def test_a_token_that_matches_means_the_deploy_is_stale(monkeypatch):
    """The one people never guess. The string is right; the image is old."""
    _refused()
    tok = "the-real-one"
    _files(monkeypatch, [{"file": "lama_clean_modal.py",
                          "app": "mangatl-clean-lama", "sha": _sha(tok)}])
    p = _P(clean_token=tok,
           clean_url="https://x--mangatl-clean-lama-cleaner-clean.modal.run")
    msg = ED.clean_warning(p)
    assert "DEPLOYED copy is out of date" in msg, msg
    assert "%s lama_clean_modal.py" % DEPLOY in msg, msg


def test_the_file_the_url_names_is_the_one_it_compares(monkeypatch):
    """Two deploy scripts sit side by side and one token is right for one of
    them. Comparing against both would say "matches" whichever address is
    actually being called."""
    _refused()
    _files(monkeypatch, [
        {"file": "lama_clean_modal.py", "app": "mangatl-clean-lama",
         "sha": _sha("lama-token")},
        {"file": "manga_clean_modal.py", "app": "mangatl-clean",
         "sha": _sha("manga-token")}])
    p = _P(clean_token="manga-token",
           clean_url="https://x--mangatl-clean-lama-cleaner-clean.modal.run")
    msg = ED.clean_warning(p)
    assert "does NOT match" in msg, msg
    assert "lama_clean_modal.py" in msg, msg


def test_with_no_deploy_file_to_hand_it_points_at_the_check(monkeypatch):
    """Somebody running the editor from somewhere else entirely. There is
    still an answer, it just costs a round trip."""
    _refused()
    _files(monkeypatch, [])
    p = _P(clean_token="whatever", clean_url="https://x.modal.run")
    msg = ED.clean_warning(p)
    assert "Test cleaner" in msg, msg


# --------------------------------------------- ...and what it must not do

def test_no_token_still_says_that_first(monkeypatch):
    """An empty box is not a 401 to diagnose; it is a box to fill in."""
    _refused()
    _files(monkeypatch, [{"file": "lama_clean_modal.py", "app": "",
                          "sha": _sha("x")}])
    msg = ED.clean_warning(_P(clean_token="", clean_url="https://x"))
    assert "Sign in" in msg, msg
    assert "deploy" not in msg.lower() and "token is saved" not in msg, msg


def test_the_example_token_still_says_that_first(monkeypatch):
    """The CHANGE-ME string out of the deploy file's comment. It IS a 401, but
    "paste the real one" beats either of the two clever answers."""
    _refused()
    _files(monkeypatch, [])
    tok = next(iter(ED.PLACEHOLDER_TOKENS)) if hasattr(ED, "PLACEHOLDER_TOKENS") \
        else None
    if tok is None:
        pytest.skip("no placeholder list to drive this from")
    msg = ED.clean_warning(_P(clean_token=tok, clean_url="https://x"))
    assert "CHANGE-ME example" in msg, msg


def test_it_says_nothing_at_all_when_the_cleaner_is_behaving():
    ED._AI_CLEAN_FAIL.update(n=0, msg="", url="", used=0, cached=0, refused="")
    assert ED.clean_warning(_P(clean_token="t", clean_url="https://x")) == ""


def test_a_failure_that_is_not_a_401_is_not_diagnosed_as_one(monkeypatch):
    """A timeout is not a token problem, and telling somebody to redeploy over
    a network blip is worse than saying nothing."""
    _refused(msg="the cleaner timed out")
    _files(monkeypatch, [{"file": "lama_clean_modal.py",
                          "app": "mangatl-clean-lama", "sha": _sha("t")}])
    msg = ED.clean_warning(_P(clean_token="t", clean_url="https://x"))
    assert "deploy" not in msg.lower(), msg
    assert "does NOT match" not in msg, msg


def test_it_never_prints_the_token(monkeypatch):
    """The warning goes in the top bar, and the top bar ends up in
    screenshots. lee sends screenshots constantly."""
    _refused()
    tok = "yq3tdiuwdgugqewyhduygwqdgduggeqywygywuegdhiuwgewebcwjhbxkjq"
    _files(monkeypatch, [{"file": "lama_clean_modal.py",
                          "app": "mangatl-clean-lama", "sha": _sha(tok)}])
    msg = ED.clean_warning(_P(clean_token=tok, clean_url="https://x"))
    assert tok not in msg, msg
    assert tok[:8] not in msg, msg
