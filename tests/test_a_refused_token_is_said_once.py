"""A cleaner that refuses the token should say so once, not forty times.

lee's console, and nothing else in it::

    Traceback (most recent call last):
      File "editor.py", line 662, in _ai_clean_call
        with urllib.request.urlopen(req, timeout=CLEAN_TIMEOUT) as resp:
      ...
    urllib.error.HTTPError: HTTP Error 401: Unauthorized

eight times over, back to back, with no sentence between them.

Two separate faults, and neither is the 401 itself -- the app already knows
exactly what a 401 means and `clean_warning` already writes the instruction
("the cleaner refused the token", plus which setting to change and why).

**It asked again for every box.** 401 and 403 are not flakes. They are the
endpoint reading the token and rejecting it, and nothing about the next region
changes the token. A chapter with forty boxes made forty round trips to be
refused forty times.

**And it printed a stack for each one.** A traceback is for a failure nobody
has diagnosed. This one is diagnosed, and forty copies of it bury the sentence
that says what to do.

So: a refusal latches for the run, keyed on the exact address and token, and
the only thing printed is one line saying it will not ask again. Paste a
different token and it asks immediately -- being told "still refused" without
the endpoint having been asked would be a lie.
"""
import urllib.error

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import editor


URL = "https://example.invalid/clean"
TOK = "a-token"


@pytest.fixture(autouse=True)
def _fresh():
    editor.clear_clean_warning()
    yield
    editor.clear_clean_warning()


@pytest.fixture()
def page():
    rng = np.random.default_rng(7)
    img = rng.integers(0, 255, (40, 40, 3), dtype=np.uint8)
    mask = np.zeros((40, 40), np.uint8)
    mask[10:20, 10:20] = 255
    return img, mask


class _Boom:
    """Counts the calls and raises whatever it was told to."""

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        raise self.exc


def _http(code):
    return urllib.error.HTTPError(URL, code, "nope", None, None)


def _call(tmp_path, img, mask, strict=False, url=URL, token=TOK):
    return editor._ai_clean_call(url, token, str(tmp_path), img, mask,
                                 strict=strict)


# --------------------------------------------------------------- the latching

@pytest.mark.parametrize("code", [401, 403])
def test_a_refused_token_is_asked_about_once(tmp_path, page, monkeypatch, code):
    """The whole point. Three boxes, one round trip."""
    img, mask = page
    boom = _Boom(_http(code))
    monkeypatch.setattr("urllib.request.urlopen", boom)
    for _ in range(3):
        _call(tmp_path, img, mask)
    assert boom.calls == 1


@pytest.mark.parametrize("code", [429, 500, 503])
def test_a_busy_or_broken_cleaner_is_asked_again(tmp_path, page, monkeypatch,
                                                 code):
    """These ARE flakes -- the endpoint is up and the token is fine, it is
    overloaded or mid-deploy. Latching them would turn a bad ten seconds into
    a chapter cleaned entirely by the local fill."""
    img, mask = page
    boom = _Boom(_http(code))
    monkeypatch.setattr("urllib.request.urlopen", boom)
    for _ in range(3):
        _call(tmp_path, img, mask)
    assert boom.calls == 3


def test_a_cleaner_that_cannot_be_reached_is_asked_again(tmp_path, page,
                                                         monkeypatch):
    """No network, or the laptop lid was shut. Nothing has been said about the
    token at all."""
    img, mask = page
    boom = _Boom(urllib.error.URLError("unreachable"))
    monkeypatch.setattr("urllib.request.urlopen", boom)
    for _ in range(3):
        _call(tmp_path, img, mask)
    assert boom.calls == 3


# ------------------------------------------------------- and letting it go

def test_a_new_token_is_tried_immediately(tmp_path, page, monkeypatch):
    """The first thing anyone does on reading the warning is paste a new
    token. Refusing to ask would be indistinguishable from the new token being
    wrong too."""
    img, mask = page
    boom = _Boom(_http(401))
    monkeypatch.setattr("urllib.request.urlopen", boom)
    _call(tmp_path, img, mask, token="old")
    _call(tmp_path, img, mask, token="old")
    assert boom.calls == 1
    _call(tmp_path, img, mask, token="new")
    assert boom.calls == 2


def test_a_new_address_is_tried_immediately(tmp_path, page, monkeypatch):
    img, mask = page
    boom = _Boom(_http(401))
    monkeypatch.setattr("urllib.request.urlopen", boom)
    _call(tmp_path, img, mask, url="https://one.invalid/x")
    _call(tmp_path, img, mask, url="https://one.invalid/x")
    assert boom.calls == 1
    _call(tmp_path, img, mask, url="https://two.invalid/x")
    assert boom.calls == 2


def test_clearing_the_warning_lets_it_ask_again(tmp_path, page, monkeypatch):
    """Saving the token or the address calls `clear_clean_warning`, and that
    has to reach this too -- otherwise redeploying the endpoint with the SAME
    token leaves the app refusing to notice for the rest of the session."""
    img, mask = page
    boom = _Boom(_http(401))
    monkeypatch.setattr("urllib.request.urlopen", boom)
    _call(tmp_path, img, mask)
    _call(tmp_path, img, mask)
    assert boom.calls == 1
    editor.clear_clean_warning()
    _call(tmp_path, img, mask)
    assert boom.calls == 2


def test_the_save_that_changes_the_token_is_the_one_that_clears_it():
    """`clear_clean_warning` is what the settings handler already calls when
    `clean_token` or `clean_url` changes. This checks the reset covers the new
    field rather than leaving it behind."""
    editor._AI_CLEAN_FAIL["refused"] = "something"
    editor.clear_clean_warning()
    assert not editor._AI_CLEAN_FAIL["refused"]


# ----------------------------------------------------------- what it prints

def test_a_refusal_does_not_print_a_stack(tmp_path, page, monkeypatch, capsys):
    """lee got eight of these and no sentence. The stack tells him where in
    urllib the exception came from, which is not a thing he can act on."""
    img, mask = page
    monkeypatch.setattr("urllib.request.urlopen", _Boom(_http(401)))
    for _ in range(3):
        _call(tmp_path, img, mask)
    out = capsys.readouterr()
    both = out.out + out.err
    assert "Traceback" not in both
    assert "401" in both, "it still says what happened"
    assert both.count("401") == 1, "once, not once per box"


def test_a_failure_nobody_has_diagnosed_still_prints_a_stack(
        tmp_path, page, monkeypatch, capsys):
    """The traceback is not noise in general -- it is the only thing there is
    for a fault with no message written for it. Quietening 401 must not
    quieten everything."""
    img, mask = page
    monkeypatch.setattr("urllib.request.urlopen", _Boom(ValueError("odd")))
    _call(tmp_path, img, mask)
    both = capsys.readouterr()
    assert "Traceback" in (both.out + both.err)


# ------------------------------------------------------- and the run goes on

def test_the_page_still_comes_back_cleaned_somehow(tmp_path, page, monkeypatch):
    """Never break a run over the network. Every skipped call still returns a
    locally filled page, the same as before."""
    img, mask = page
    monkeypatch.setattr("urllib.request.urlopen", _Boom(_http(401)))
    first = _call(tmp_path, img, mask)
    second = _call(tmp_path, img, mask)
    assert first.shape == img.shape
    assert second.shape == img.shape


def test_every_skipped_box_is_still_counted(tmp_path, page, monkeypatch):
    """The warning says how many spots were filled in locally. Not asking the
    endpoint must not make those spots invisible -- they were still cleaned the
    plain way and lee still needs to know how much of the page that is."""
    img, mask = page
    monkeypatch.setattr("urllib.request.urlopen", _Boom(_http(401)))
    for _ in range(4):
        _call(tmp_path, img, mask)
    assert editor._AI_CLEAN_FAIL["n"] == 4
    assert "401" in editor._AI_CLEAN_FAIL["msg"]


def test_a_single_healed_spot_is_told_rather_than_downgraded(tmp_path, page,
                                                             monkeypatch):
    """`strict` means the caller has a local method BETTER than Telea and needs
    to know the endpoint is out. A latched refusal has to raise for the same
    reason the first one did, or Heal quietly gets worse after the first
    failure."""
    img, mask = page
    monkeypatch.setattr("urllib.request.urlopen", _Boom(_http(401)))
    with pytest.raises(Exception):
        _call(tmp_path, img, mask, strict=True)
    with pytest.raises(Exception):
        _call(tmp_path, img, mask, strict=True)


def test_the_raised_refusal_says_what_happened(tmp_path, page, monkeypatch):
    """Whatever catches it puts the message in front of a person."""
    img, mask = page
    monkeypatch.setattr("urllib.request.urlopen", _Boom(_http(401)))
    with pytest.raises(Exception):
        _call(tmp_path, img, mask, strict=True)
    with pytest.raises(Exception, match="401"):
        _call(tmp_path, img, mask, strict=True)
