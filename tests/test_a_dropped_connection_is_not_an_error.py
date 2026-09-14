"""A kept-open connection the window puts down is not a traceback.

1.0.10 turned on HTTP/1.1 keep-alive, so a connection now spends most of its
life waiting in `handle_one_request` for the next request. The window drops idle
ones whenever it likes, and that arrives as a reset in the READ - outside
`_send`, which is where `Handler.GONE` was already caught. The editor's log on
lee's machine the morning after 1.0.11 had nothing in it but one of these:
`ConnectionResetError: [WinError 10054]`, from `rfile.readline`.
"""
from http.server import BaseHTTPRequestHandler

import pytest


def _handler():
    from mangatl import editor
    h = editor.Handler.__new__(editor.Handler)
    h.close_connection = False
    return editor, h


@pytest.mark.parametrize("gone", [ConnectionResetError, ConnectionAbortedError,
                                  BrokenPipeError])
def test_the_client_going_away_closes_quietly(monkeypatch, gone):
    def read_fails(self):
        raise gone(10054, "An existing connection was forcibly closed")
    monkeypatch.setattr(BaseHTTPRequestHandler, "handle_one_request", read_fails)
    editor, h = _handler()
    editor.Handler.handle_one_request(h)       # must not raise
    assert h.close_connection is True


def test_anything_else_is_still_an_error(monkeypatch):
    """Only the client leaving is quiet. A real fault must still surface."""
    def broken(self):
        raise ValueError("a real bug")
    monkeypatch.setattr(BaseHTTPRequestHandler, "handle_one_request", broken)
    editor, h = _handler()
    with pytest.raises(ValueError):
        editor.Handler.handle_one_request(h)
