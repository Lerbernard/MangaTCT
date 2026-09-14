"""Only the app's own window gets MangaTCT - not another browser, not a website.

lee: *"i notice that http://127.0.0.1:8765/ is live on the app when the app is
runnibg we dont need a web version running too"*.

The window is a browser showing the editor's local server, so the server has to
be there. What changed is who it answers (see `editor.APP_KEY`):

* a request from some other page - a foreign Host or Origin - is refused,
  always;
* the editor leaves a key for this start in the person's own folder, the window
  opens the page with it once, and from then on nothing without the cookie that
  visit set is answered, except `/api/version`, which the launcher polls.

Until a window has used the key, nothing is locked, so a start with no window
(no WebView2, `--browser`, a checkout run from a terminal) is still a page in
the browser.
"""
import http.client
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from where import PKG


@pytest.fixture()
def server(tmp_path):
    from mangatl import editor
    from mangatl.project import Project
    p = Project(None, str(tmp_path / "proj"))
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        yield editor, port
    finally:
        editor.APP_KEY.update(key="", claimed=False)
        editor.forget_app_key(port)
        srv.shutdown()
        srv.server_close()
        editor.PROJECT = was


def _ask(port, path="/", method="GET", headers=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        c.close()


def _claim(editor, port):
    key = editor.make_app_key(port)
    status, head, _ = _ask(port, "/?app_key=" + key)
    cookie = head.get("Set-Cookie", "").split(";")[0]
    return key, status, head, cookie


# ------------------------------------------------------ before a window claims

def test_with_no_window_the_browser_still_works(server):
    """No WebView2, `--browser`, a checkout from a terminal: nobody ever uses
    the key, so nothing is locked."""
    editor, port = server
    editor.make_app_key(port)
    status, _, body = _ask(port, "/")
    assert status == 200, status
    assert b"open in its own window" not in body


def test_a_website_is_refused_even_with_no_key_at_all(server):
    """A form post from a site in any browser, or a site that points its own
    name at 127.0.0.1."""
    editor, port = server
    s, _, _ = _ask(port, "/api/version", headers={"Host": "evil.example:%d" % port})
    assert s == 403
    s, _, _ = _ask(port, "/api/project", method="POST", body=b"{}",
                   headers={"Origin": "https://evil.example",
                            "Content-Type": "application/json"})
    assert s == 403
    s, _, _ = _ask(port, "/api/version",
                   headers={"Origin": "http://127.0.0.1:%d" % port})
    assert s == 200, "the editor's own page must not be refused"


# ------------------------------------------------------------ the window claims

def test_the_key_is_swapped_for_a_cookie_and_leaves_the_address(server):
    editor, port = server
    key, status, head, cookie = _claim(editor, port)
    assert status == 303
    assert head["Location"] == "/", head
    assert cookie == "%s=%s" % (editor.APP_COOKIE, key)
    flags = head["Set-Cookie"].lower()
    assert "httponly" in flags and "samesite=strict" in flags, flags
    assert editor.APP_KEY["claimed"]


def test_after_that_only_the_window_is_answered(server):
    editor, port = server
    _key, _s, _h, cookie = _claim(editor, port)
    s, head, body = _ask(port, "/")
    assert s == 403 and b"open in its own window" in body
    s, _, _ = _ask(port, "/api/project")
    assert s == 403
    s, _, _ = _ask(port, "/", headers={"Cookie": cookie})
    assert s == 200
    s, _, _ = _ask(port, "/api/version")
    assert s == 200, "the launcher polls this and has no cookie"


def test_a_wrong_key_opens_nothing(server):
    editor, port = server
    editor.make_app_key(port)
    s, _, _ = _ask(port, "/?app_key=not-the-key")
    assert s == 403
    assert not editor.APP_KEY["claimed"]


def test_every_start_has_a_new_key_and_an_old_cookie_is_no_use(server):
    """The window keeps its cookies between starts. Yesterday's is not today's."""
    editor, port = server
    _k, _s, _h, old = _claim(editor, port)
    editor.make_app_key(port)
    _ask(port, "/?app_key=" + editor.APP_KEY["key"])       # today's window
    s, _, _ = _ask(port, "/", headers={"Cookie": old})
    assert s == 403


# ------------------------------------------------------------- the window's side

def test_the_window_reads_the_key_the_editor_left(server):
    from mangatl import window as W
    editor, port = server
    key = editor.make_app_key(port)
    assert W.app_key(port, wait=0) == key
    assert Path(editor.app_key_file(port)).name == "window-%d.key" % port
    a = W.parse(["--port", str(port)])
    assert W.url_for(a, key) == "http://127.0.0.1:%d/?app_key=%s" % (port, key)
    assert W.url_for(a) == "http://127.0.0.1:%d/" % port


def test_no_key_file_is_no_key_and_no_wait(server):
    from mangatl import window as W
    editor, port = server
    editor.forget_app_key(port)
    assert W.app_key(port, wait=0) == ""


def test_the_key_is_made_before_the_port_opens_and_gone_after():
    src = (PKG / "editor.py").read_text("utf-8")
    main = src[src.index("def main(argv=None)"):]
    assert main.index("make_app_key(a.port)") < main.index("serve_forever()")
    assert "atexit.register(forget_app_key, a.port)" in main
    win = (PKG / "window.py").read_text("utf-8")
    assert "url_for(a, app_key(a.port))" in win


# ------------------------------------------------------------------ the launcher

def test_the_launcher_offers_no_browser_button():
    src = (PKG / "launcher" / "mangatct_launcher.py").read_text("utf-8")
    assert 'text="Open in browser"' not in src
    assert "b_open" not in src
    assert "is running at http" not in src
