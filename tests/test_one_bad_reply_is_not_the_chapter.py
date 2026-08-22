"""One malformed reply must not end the run.

lee, after reading a 58-page chapter a crop per box::

    the linking worked gret the only error was this, JSONDecodeError:
    Expecting property name enclosed in double quotes: line 1 column 21
    (char 20) (translate.py:885 in _extract_json)

**That column number is not vague - it names the reply exactly.** Character 20
is the end of ``{"regions":[{"id":0,`` and the parser is asking for the next
KEY. Two shapes give that message to the character, and both are reproduced in
the tests below: the key left bare (``,translation:``) and the key in single
quotes (``,'translation':``). Nothing else of that length does.

Two things were wrong and both are fixed here.

**The reader had no retry.** `translate_page` and `proofread_page` both catch a
bad reply, tell the model what was wrong and ask again. `read_page_ocr` parsed
straight through, so one bad reply raised out of `do_ocr`, out of the job, and
took the other 57 pages with it. It asks again now, `OCR_TRIES` times.

**And when it still will not parse, the piece is skipped, not thrown.** Its
regions come back unread - `do_ocr` flags them "ocr: no text read", which is
the red box lee already knows how to fix - and the rest of the chapter
finishes.

Why a crop per box is where this showed up: a dozen pictures ride in one turn,
so one reply carries a dozen entries. There is simply more of it to get wrong
than in the one-region-per-tile replies that never tripped it.
"""
import json

import pytest

from mangatl import translate as T


# ------------------------------------------------- the reply that took it down

def test_lees_error_is_the_bare_key():
    """Not a guess at the shape - the message matches to the character."""
    with pytest.raises(json.JSONDecodeError) as e:
        json.loads('{"regions":[{"id":0,translation:"x"}]}')
    assert "Expecting property name enclosed in double quotes" in str(e.value)
    assert "line 1 column 21 (char 20)" in str(e.value)


def test_and_the_single_quoted_key_gives_the_same_message():
    with pytest.raises(json.JSONDecodeError) as e:
        json.loads("{\"regions\":[{\"id\":0,'translation':\"x\"}]}")
    assert "line 1 column 21 (char 20)" in str(e.value)


def test_a_bare_key_is_read():
    d = T._extract_json('{"regions":[{"id":0,translation:"x"}]}')
    assert d == {"regions": [{"id": 0, "translation": "x"}]}


def test_a_single_quoted_key_is_read():
    d = T._extract_json("{\"regions\":[{\"id\":0,'translation':\"x\"}]}")
    assert d == {"regions": [{"id": 0, "translation": "x"}]}


def test_a_reply_with_no_quoted_keys_at_all_is_read():
    d = T._extract_json('{regions:[{id:0, text: "음......."}], page_notes:""}')
    assert d["regions"][0]["text"] == "음......."
    assert d["page_notes"] == ""


def test_a_single_quoted_line_is_read_too():
    """A single quote outside a string is a string delimiter wherever it is.

    The key is what broke lee's run, but a model that puts single quotes round
    a key puts them round a line just as readily, and there is nothing to lose
    by fixing both."""
    d = T._extract_json("{\"regions\":[{\"id\":0,\"text\":'네, 스승님.'}]}")
    assert d["regions"][0]["text"] == "네, 스승님."


def test_a_bare_word_in_a_VALUE_is_still_a_failure():
    """A bareword is only quoted where a COLON follows it - where it can be a
    key. Anywhere else it is `null`, `true` or a number, and quoting those
    would turn "speaker":null into the string "null" on every page of the
    chapter. A bareword that is a real mistake stays a mistake and the reply
    is asked for again, which beats believing it."""
    with pytest.raises(Exception):
        T._extract_json('{"regions":[{"id":0,"text":no idea}]}')


def test_the_json_words_are_left_alone():
    """`null`, `true` and a number are barewords in value position, and every
    reply is full of them."""
    d = T._extract_json('{"regions":[{"id":0,"speaker":null,"ok":true,'
                        '"confidence":0.9}]}')
    r = d["regions"][0]
    assert r["speaker"] is None and r["ok"] is True and r["confidence"] == 0.9


def test_the_repairs_that_were_already_there_still_work():
    """A quote inside a line, a raw newline, smart quotes, trailing commas."""
    assert T._extract_json(
        '{"regions":[{"id":0,"text":"He said "stop" now"}]}'
    )["regions"][0]["text"] == 'He said "stop" now'
    assert T._extract_json('{"a": "one\ntwo"}')["a"] == "one\ntwo"
    assert T._extract_json('{“a”: “b”}') == {"a": "b"}
    assert T._extract_json('{"a": 1, "b": [1, 2,], }') == {"a": 1, "b": [1, 2]}
    assert T._extract_json('Here you go:\n```json\n{"a": 1}\n```') == {"a": 1}


def test_an_apostrophe_inside_a_line_is_not_a_key_hunt():
    d = T._extract_json('{"a": "it\'s fine", "b": "x, y: z"}')
    assert d == {"a": "it's fine", "b": "x, y: z"}


# ------------------------------------------------------- ...and the retry loop

class _Page:
    pass


def _page(n=2):
    import numpy as np

    from mangatl.models import Page, TextRegion
    p = Page(image=np.full((400, 300, 3), 245, "uint8"), source_path="t.png")
    rs = []
    for i in range(n):
        r = TextRegion(id=i, bbox=(10, 10 + i * 100, 80, 40), text_mask=None,
                       bubble_mask=None, bubble_bbox=(10, 10 + i * 100, 80, 40),
                       kind="bubble")
        r.order = i
        rs.append(r)
    p.regions = rs
    return p


class _Ctx:
    backend = "anthropic"; base_url = ""; model = "m"; api_key = "k"
    medium = "manhwa"; source = "Korean"; glossary = {}; characters = {}
    safety = ""; step_name = ""


def _run(replies, tiles=None, batch=1, monkeypatch=None):
    """Drive `read_page_ocr` with a scripted list of raw model replies."""
    said = []

    def fake(client, kind, model, system, user, image_b64,
             media_type="image/png"):
        said.append(user)
        return replies[min(len(said) - 1, len(replies) - 1)]

    monkeypatch.setattr(T, "_ask_vision", fake)
    p = _page()
    tiles = tiles or [(b"png-0", [0]), (b"png-1", [1])]
    got = T.read_page_ocr(p, _Ctx(), tiles, client=object(), model="m",
                          batch=batch)
    return got, said


def test_a_bad_reply_is_asked_again(monkeypatch):
    got, said = _run(['I could not read that page, sorry!',
                      '{"regions":[{"id":0,"text":"first"}]}',
                      '{"regions":[{"id":1,"text":"second"}]}'],
                     monkeypatch=monkeypatch)
    assert got == {0: "first", 1: "second"}, got
    assert len(said) == 3, "the bad reply was not asked again"


def test_and_the_second_ask_says_what_was_wrong(monkeypatch):
    """A retry that repeats the same words gets the same reply."""
    _got, said = _run(['not json at all',
                       '{"regions":[{"id":0,"text":"x"}]}'],
                      monkeypatch=monkeypatch)
    assert "could not be read as JSON" in said[1]
    assert said[1].startswith(said[0]), "the retry dropped the original ask"
    assert "could not be read as JSON" not in said[0]


def test_a_piece_that_never_parses_is_skipped_not_thrown(monkeypatch):
    """The whole point. Page 12 losing a box must not lose pages 13 to 71."""
    replies = ['{"regions":[{"id":0,"text":"kept"}]}'] * 1
    calls = {"n": 0}

    def fake(client, kind, model, system, user, image_b64,
             media_type="image/png"):
        calls["n"] += 1
        # the FIRST piece answers; the second never does
        return ('{"regions":[{"id":0,"text":"kept"}]}'
                if "outlined in red: 0" in user or calls["n"] == 1
                else 'sorry, no')

    monkeypatch.setattr(T, "_ask_vision", fake)
    got = T.read_page_ocr(_page(), _Ctx(),
                          [(b"a", [0]), (b"b", [1])],
                          client=object(), model="m")
    assert got == {0: "kept"}, got
    assert 1 not in got, "the unreadable piece must come back unread, not wrong"
    assert calls["n"] == 1 + T.OCR_TRIES, calls


def test_it_gives_up_rather_than_asking_forever(monkeypatch):
    assert 1 < T.OCR_TRIES <= 5


def test_the_other_two_steps_already_had_this():
    """Written down so nobody 'tidies' the reader back to matching them by
    taking the retry OUT."""
    import inspect
    for fn in (T.translate_page, T.proofread_page):
        src = inspect.getsource(fn)
        assert "_extract_json" in src and "except Exception" in src, fn.__name__
