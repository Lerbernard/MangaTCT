"""The file you download is the request the app would have sent.

`/api/translate_request` exists so a chapter can be run through any AI the
person likes. "The exact request the translator would send" is what its own
comment promised, and for a long time it was not true: it built its own region
dicts out of the saved records, beside `translate.build_payload`, and the two
drifted.

lee sent back a Translate request exported off his own 23-page chapter. Against
what the live run sends, the file was missing five things:

    fits_chars           how much English that balloon holds. (Gone from the
                         payload altogether now - see below - but it was the
                         loudest of the five when this was written, and the
                         reason the endpoint had to stop building its own
                         regions.)
    link / balloon       so a pair he had linked by hand arrived as two
                         unrelated boxes
    previous_page_tail   hardcoded to [], so every page was translated with no
                         memory of the page before it
    chapter_context
    already_said

There is one payload now, and this endpoint asks for it. That is the whole
fix, and this file is the thing that was never here: **there was no test on
this endpoint at all**, which is how a second copy of the request shape lived
beside the first for as long as it did.

It cost a materialise a page, about three quarters of a second, because
`fits_chars` measured the BALLOON and the balloon's mask is not in the record.

**`fits_chars` has since left the payload entirely** - lee: *"i wan the most
accurate transaltion no matter the leght of the of it so i dont want to shrink
or expand teh translation to fit anythng"* - so that cost is no longer being
paid for a number nobody sends. What this file is still for is the shape: one
payload, built in one place, and this endpoint asking for it rather than
writing its own.
"""
import json

import pytest

from where import PKG


def _endpoint() -> str:
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    at = src.index('if path == "/api/translate_request":')
    return src[at:src.index('\n            m = re.fullmatch', at)]


# ------------------------------------------------- one payload, not two

def test_it_asks_build_payload_rather_than_writing_its_own():
    body = _endpoint()
    assert "build_payload(" in body


def test_no_region_dict_is_assembled_here():
    """The specific shape that drifted. A literal `src_char_count` in this
    block means somebody has started a second copy again."""
    body = _endpoint()
    assert '"src_char_count"' not in body
    assert '"target_language"' not in body, \
        "the top half of the payload is being rebuilt here too"


def test_the_page_tail_is_carried_and_not_stubbed():
    body = _endpoint()
    assert "_page_tail(p, i - 1)" in body
    assert '"previous_page_tail": []' not in body


def test_the_chapter_context_goes_with_it():
    """The live run passes what the rest of the chapter said. A download that
    leaves it out is cheaper and answers a different question."""
    body = _endpoint()
    assert "run_context(p, idxs)" in body
    assert "chapter)" in body


def test_the_settings_are_read_the_way_a_run_reads_them():
    """Three fields were being set by hand. That is how `keep_honorifics`, the
    story switches and the font sizes went missing from the file."""
    body = _endpoint()
    assert '_ctx_from_settings(p, "translate")' in body
    assert "p.ctx.medium =" not in body


def test_the_reason_for_the_materialise_is_written_down():
    """It is the one cost this fix adds, and the next person to see it will
    want to take it out again."""
    body = _endpoint()
    flat = " ".join(body.split())
    assert "materialise" in flat
    assert "bubble_bbox" in flat and "48" in flat


# ------------------------------------------------------------- and it runs

def _serve(fn, root=None):
    import json as _json
    import shutil
    import threading
    from http.server import ThreadingHTTPServer
    import urllib.request

    import numpy as np
    cv2 = pytest.importorskip("cv2")
    from scratch import scratch
    from mangatl import editor
    from mangatl.project import Project

    root = root or scratch("_tmp_req")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.add_uploaded("a.png", cv2.imencode(
        ".png", np.full((400, 300, 3), 240, np.uint8))[1].tobytes())
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def get(path):
        with urllib.request.urlopen(base + path, timeout=30) as r:
            return _json.loads(r.read())
    try:
        return fn(p, get)
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def _one_box(p):
    """A page with one region that has been read, committed the way the app
    commits one."""
    page = p.materialize(0)
    from mangatl.models import TextRegion
    r = TextRegion(id=1, bbox=(40, 40, 120, 200), kind="bubble", order=0,
                   src_text="こんにちは")
    page.regions = [r]
    p.commit(0, page)


def test_the_download_carries_no_length_budget_because_the_run_does_not():
    """The point of this file is that the two are the SAME payload, so when
    `fits_chars` and `src_char_count` came out of `build_payload` they came
    out of the download in the same move, with nothing edited here.

    That is worth a test of its own: the version of this endpoint that built
    its own region dicts would have gone on sending whatever it had been
    written to send, for as long as nobody looked."""
    def check(p, get):
        _one_box(p)
        got = get("/api/translate_request")
        regs = got["pages"][0]["request"]["regions"]
        assert regs, got
        assert "fits_chars" not in regs[0], regs[0]
        assert "src_char_count" not in regs[0], regs[0]
        assert regs[0]["text"], "the words themselves still travel"
    _serve(check)


def test_a_linked_pair_arrives_linked():
    def check(p, get):
        from mangatl.models import TextRegion
        page = p.materialize(0)
        page.regions = [
            TextRegion(id=1, bbox=(10, 10, 100, 120), kind="bubble", order=0,
                       src_text="これは", link=3),
            TextRegion(id=2, bbox=(10, 150, 100, 120), kind="bubble", order=1,
                       src_text="つづきです", link=3)]
        p.commit(0, page)
        regs = get("/api/translate_request")["pages"][0]["request"]["regions"]
        assert all(r.get("link") == 3 or r.get("balloon") == 3 for r in regs), \
            regs
    _serve(check)


def test_the_file_still_says_how_to_use_it():
    def check(p, get):
        _one_box(p)
        got = get("/api/translate_request")
        assert "how_to_use" in got and "system" in got
        assert "response_schema" in got
        assert got["pages"][0]["response"] is None
        assert got["pages"][0]["page_name"]
    _serve(check)


def test_a_page_with_nothing_read_on_it_is_left_out():
    def check(p, get):
        got = get("/api/translate_request")
        assert got["pages"] == []
    _serve(check)


def test_it_matches_what_the_live_run_would_build(monkeypatch):
    """The promise, tested as a promise: the request in the file and the
    request `translate_page` builds for the same page are the same object."""
    def check(p, get):
        _one_box(p)
        from mangatl import editor
        from mangatl.translate import build_payload
        got = get("/api/translate_request")["pages"][0]["request"]
        editor._ctx_from_settings(p, "translate")
        p.ctx.previous_page_tail = editor._page_tail(p, -1)
        mine = build_payload(p.materialize(0), p.ctx,
                             editor.run_context(p, [0]))
        assert json.dumps(got, sort_keys=True, ensure_ascii=False) == \
            json.dumps(mine, sort_keys=True, ensure_ascii=False)
    _serve(check)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
