"""A request that goes quiet is sent again.

lee's proofread of a chapter died on one page with a `TimeoutError` raised out
of `ssl.py`, thirty lines of stack ending in `self._sslobj.read`. The run
stopped there. Pages 1 to 11 were saved and the rest were refunded, so nothing
was lost and nothing was overcharged - but the run ended, and the reason a
person could see was a traceback about a socket.

The loop already retried a 429, a 500 and a 503. It did not retry the one
failure that is *always* worth retrying: nothing was refused, nothing was wrong
with the request, the answer simply did not come back. A read timeout is not an
answer of any kind.

Two budgets, deliberately separate. A rate limit comes back in milliseconds and
six retries cost nothing; a timeout costs a whole `timeout` of waiting each
time, so six of them is half an hour of somebody watching a bar that is not
moving.
"""
import http.client
import urllib.error

import pytest

from mangatl import translate as t


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """The backoff is real and this suite is not paying for it."""
    monkeypatch.setattr("time.sleep", lambda *_a: None)


def client(timeout=300):
    return t.OpenAICompatClient("http://x/v1", "gemini-3.6-flash", "k",
                                timeout=timeout)


def replies(*answers):
    """A fake `urlopen` that raises or returns, one per call, and counts."""
    calls = []

    class Body:
        def __init__(self, text):
            self.text = text

        def read(self):
            return self.text.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=0):
        calls.append(timeout)
        nxt = answers[min(len(calls) - 1, len(answers) - 1)]
        if isinstance(nxt, Exception):
            raise nxt
        return Body(nxt)

    fake.calls = calls
    return fake


OK = '{"choices":[{"message":{"content":"the answer"}}]}'


# --------------------------------------------------------------- what retries

def test_a_read_timeout_is_tried_again(monkeypatch):
    """The exact failure lee saw: the connection is up, the request was
    accepted, and nothing comes back."""
    fake = replies(TimeoutError("The read operation timed out"), OK)
    monkeypatch.setattr("urllib.request.urlopen", fake)
    assert client().complete("sys", "user") == "the answer"
    assert len(fake.calls) == 2


def test_a_timeout_while_connecting_is_tried_again(monkeypatch):
    """A slow CONNECT arrives wrapped in a URLError; a slow READ arrives bare.
    Same failure, two shapes, and only one of them was ever handled."""
    fake = replies(urllib.error.URLError(TimeoutError()), OK)
    monkeypatch.setattr("urllib.request.urlopen", fake)
    assert client().complete("sys", "user") == "the answer"
    assert len(fake.calls) == 2


@pytest.mark.parametrize("boom", [
    ConnectionResetError("reset by peer"),
    http.client.RemoteDisconnected("closed without a reply"),
    http.client.IncompleteRead(b"half"),
])
def test_a_connection_that_goes_away_mid_answer_is_tried_again(monkeypatch, boom):
    """All the same shape of failure: accepted, then silence. A long completion
    is exactly when a connection gets dropped by something in the middle."""
    fake = replies(boom, OK)
    monkeypatch.setattr("urllib.request.urlopen", fake)
    assert client().complete("sys", "user") == "the answer"
    assert len(fake.calls) == 2


def test_it_gives_up_after_three_and_says_so_in_words(monkeypatch):
    """Three, not six. Each one costs a whole timeout of waiting."""
    fake = replies(TimeoutError("timed out"))
    monkeypatch.setattr("urllib.request.urlopen", fake)
    with pytest.raises(RuntimeError) as bad:
        client(timeout=120).complete("sys", "user")
    assert len(fake.calls) == t.SLOW_TRIES == 3

    says = str(bad.value)
    # It has to name the model and the wait, or it is not actionable.
    assert "gemini-3.6-flash" in says
    assert "120 seconds" in says
    # ...and say the two things a person is worried about at that moment.
    assert "saved" in says and "refunded" in says
    # ...and it must not read like a crash.
    for jargon in ("Traceback", "ssl", "socket", "_sslobj", "recv_into"):
        assert jargon not in says, says


def test_the_reader_retries_the_same_way(monkeypatch):
    """`complete_vision` is a second copy of the same loop, which is exactly
    how one of them ends up fixed and the other does not."""
    fake = replies(TimeoutError("timed out"), OK)
    monkeypatch.setattr("urllib.request.urlopen", fake)
    got = client().complete_vision("sys", "user", "aGk=")
    assert got == "the answer"
    assert len(fake.calls) == 2


def test_the_reader_gives_up_in_words_too(monkeypatch):
    fake = replies(TimeoutError("timed out"))
    monkeypatch.setattr("urllib.request.urlopen", fake)
    with pytest.raises(RuntimeError) as bad:
        client(timeout=90).complete_vision("sys", "user", "aGk=")
    assert len(fake.calls) == 3
    assert "90 seconds" in str(bad.value)


# ----------------------------------------------------------- what does not

def test_a_dead_address_is_not_retried_three_times(monkeypatch):
    """A name that does not resolve will not resolve in three seconds either.
    Retrying it is three times the wait for the same answer, and the message
    is one somebody can act on immediately."""
    fake = replies(urllib.error.URLError("name or service not known"))
    monkeypatch.setattr("urllib.request.urlopen", fake)
    with pytest.raises(RuntimeError) as bad:
        client().complete("sys", "user")
    assert len(fake.calls) == 1
    assert "could not reach" in str(bad.value)


def test_a_refusal_is_still_a_refusal(monkeypatch):
    """404 is the model being gone, not the model being slow. It must not be
    swallowed into the retry loop and it must not be retried."""
    fake = replies(urllib.error.HTTPError(
        "u", 404, "not found", {}, None))
    monkeypatch.setattr("urllib.request.urlopen", fake)
    with pytest.raises(RuntimeError) as bad:
        client().complete("sys", "user")
    assert len(fake.calls) == 1
    assert "did not answer within" not in str(bad.value)


def test_the_rate_limit_budget_is_not_the_timeout_budget(monkeypatch):
    """Six 429s are cheap and are still allowed. The two counters must not
    share, or one slow page would eat the retries a rate-limited page needs.
    """
    hdrs = {"retry-after": "0"}
    fake = replies(*([urllib.error.HTTPError("u", 429, "slow down", hdrs, None)] * 5
                     + [OK]))
    monkeypatch.setattr("urllib.request.urlopen", fake)
    assert client().complete("sys", "user") == "the answer"
    assert len(fake.calls) == 6


def test_something_that_is_neither_comes_back_unchanged(monkeypatch):
    """The new branch catches everything, so it has to re-raise what it does
    not recognise. A bug in the reply parser must not come back dressed as a
    timeout."""
    class Odd(Exception):
        pass

    fake = replies(Odd("something else entirely"))
    monkeypatch.setattr("urllib.request.urlopen", fake)
    with pytest.raises(Odd):
        client().complete("sys", "user")
    assert len(fake.calls) == 1


# ---------------------------------------------------------------- the test

def test_what_counts_as_going_quiet():
    quiet = [TimeoutError(), ConnectionResetError(), ConnectionAbortedError(),
             http.client.RemoteDisconnected(), http.client.BadStatusLine("x"),
             urllib.error.URLError(TimeoutError()),
             urllib.error.URLError(ConnectionResetError())]
    for e in quiet:
        assert t._went_quiet(e), e

    loud = [urllib.error.URLError("name not known"),
            urllib.error.HTTPError("u", 404, "no", {}, None),
            urllib.error.HTTPError("u", 429, "no", {}, None),
            ValueError("bad json"), RuntimeError("refused")]
    for e in loud:
        assert not t._went_quiet(e), e
