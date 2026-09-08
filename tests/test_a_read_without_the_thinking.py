"""The reader turns Claude 5's thinking off, and the quote knows it did.

Task #125 found that Opus 5 reasons on a read unless told not to - five sixths
of its output on lee's 58-page manhwa, sixteen thousand tokens nobody saw,
billed as output and reported nowhere. About 80 of the read's 274 coins.

lee: *"turn it of ad let me do a run and compare"*.

So `translate._create_read` sends `thinking: {"type": "disabled"}` for the
models on `coins.READ_THINKING_OFF`, and `coins.thinks` quotes those models
without reasoning on the `ocr` step. ONE list, read by both: the request and
the price cannot disagree about the same call.

Three things this must get right, in order of how expensive it is to get them
wrong:

* The knob is sent for exactly the models that accept it. Opus 5 and Sonnet 5
  do; Fable 5 and the Mythos line reject it (Anthropic: *"Thinking can't be
  turned off on these models"*), and a 400 on every page is a chapter that
  cannot be read.
* A model that refuses anyway is read with thinking ON, once, remembered, and
  said out loud - the person comparing a thinking read to a non-thinking one
  has to know which they got.
* `coins.drift` must not mix the two regimes. The same model on the same step
  produced 19,576 output tokens with thinking and will produce about 3,600
  without; a line from the old regime voting on the new quote drags it up
  2.5x for eight runs. Lines carry `think_off`, and drift reads only its own.

The read that scored 0 dialogue errors was a thinking read. lee ran the other
kind the next day, same 58 pages, and it lost: 190 coins against 274, and for
the 84 saved, two dialogue errors on clean printed type (page 012's balloon
came back without its second line, `오빠!`; page 009's `이었음을` came back
`이였음을`) and five more sound effects missed. Both dialogue errors were the
ones Gemini made on the same boxes - without its thinking, Opus reads like a
cheaper model. So `READ_THINKING_OFF` is empty, the machinery stays, and one
name in the tuple switches it back.

The tests below are therefore written against the MACHINERY, with the tuple
set by the test, so they hold whatever is in it on the day.
"""
import pytest

from mangatl import coins
from mangatl import translate as t


@pytest.fixture(autouse=True)
def purse(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path / "home"))
    t._NO_THINKING_OFF.clear()
    t._NO_TEMPERATURE.clear()
    return tmp_path


@pytest.fixture
def knob_on(monkeypatch):
    """The list as it stood for lee's comparison run."""
    monkeypatch.setattr(coins, "READ_THINKING_OFF",
                        ("claude-opus-5", "claude-sonnet-5"))


# ------------------------------------------------------------ one list, two readers

def test_the_verdict_thinking_stays_on_for_reads():
    """The measured answer, held so nobody re-buys the 84 coins by accident.
    Reads on Opus 5 think, and are quoted for it."""
    assert coins.READ_THINKING_OFF == ()
    assert not coins.read_thinks_off("claude-opus-5")
    assert coins.thinks("claude-opus-5", "anthropic", "ocr") is True


def test_the_list_names_the_models_that_accept_the_knob(knob_on):
    assert coins.read_thinks_off("claude-opus-5")
    assert coins.read_thinks_off("claude-sonnet-5")
    assert coins.read_thinks_off("anthropic/claude-opus-5"), "vendor prefix"
    # Fable and Mythos reject the parameter; Claude 4 never thought unasked;
    # nothing else is Anthropic's to switch.
    for m in ("claude-fable-5", "claude-opus-4", "claude-haiku-4-5",
              "gemini-3.8-flash", "qwen/qwen3.7-plus"):
        assert not coins.read_thinks_off(m), m


def test_the_quote_reads_the_same_list_as_the_request(knob_on):
    """A read on a listed model is quoted without reasoning; a translate on
    the same model is still quoted with it - the knob is a READ knob."""
    assert coins.thinks("claude-opus-5", "anthropic", "ocr") is False
    assert coins.thinks("claude-opus-5", "anthropic", "translate") is True
    assert coins.think_tokens(coins.SHAPES["ocr"], "claude-opus-5",
                              "anthropic", 144, "ocr") == 0
    # ...and a model that cannot have it turned off is quoted for thinking on
    # a read, because that is what it will do.
    assert coins.thinks("claude-fable-5", "anthropic", "ocr") is True


def test_the_list_outranks_the_meter_because_anthropics_meter_never_speaks(knob_on):
    """Even a ledger line claiming Opus reported reasoning on a read - which
    Anthropic cannot produce - does not make a disabled read a thinking
    quote. What the app asks for is the fact here."""
    coins.note("ocr cost", "p", "claude-opus-5", step="ocr",
               backend="openrouter", boxes=144, pages=58, tin=1, tout=1,
               think=16_000, calls=1, coins=1, charged=1)
    assert coins.thinks("claude-opus-5", "openrouter", "ocr") is False


# -------------------------------------------------------------- the request

class _Client:
    """A fake Anthropic client that records what it was asked and can be
    told which knobs to refuse."""

    def __init__(self, refuse=()):
        self.calls = []
        self.refuse = tuple(refuse)
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        for knob, words in (("temperature", "temperature is deprecated"),
                            ("thinking", "thinking cannot be disabled")):
            if knob in kw and knob in self.refuse:
                raise RuntimeError(f"400: {words} for this model")

        class R:
            content = []
            usage = None
        return R()


def _kw(model):
    return dict(model=model, max_tokens=10, system=[], messages=[])


def test_a_read_on_opus_asks_for_thinking_off_and_temperature_zero(knob_on):
    c = _Client()
    t._create_read(c, "claude-opus-5", _kw("claude-opus-5"))
    assert len(c.calls) == 1
    assert c.calls[0]["thinking"] == {"type": "disabled"}
    assert c.calls[0]["temperature"] == 0


def test_a_read_on_a_model_off_the_list_does_not_ask(knob_on):
    for model in ("claude-fable-5", "claude-haiku-4-5"):
        c = _Client()
        t._create_read(c, model, _kw(model))
        assert "thinking" not in c.calls[0], model
        assert c.calls[0]["temperature"] == 0, model


def test_a_refusal_drops_the_knob_and_is_remembered(knob_on, capsys):
    """Read with thinking on, once, remembered, and said out loud."""
    c = _Client(refuse=("thinking",))
    t._create_read(c, "claude-sonnet-5", _kw("claude-sonnet-5"))
    assert len(c.calls) == 2
    assert "thinking" in c.calls[0] and "thinking" not in c.calls[1]
    assert c.calls[1]["temperature"] == 0, "the other knob survived"
    assert "claude-sonnet-5" in t._NO_THINKING_OFF
    said = capsys.readouterr().out
    assert "would not turn its thinking off" in said
    assert "reading with it on" in said
    # the next page does not try again
    c2 = _Client(refuse=("thinking",))
    t._create_read(c2, "claude-sonnet-5", _kw("claude-sonnet-5"))
    assert len(c2.calls) == 1 and "thinking" not in c2.calls[0]


def test_each_knob_is_dropped_on_its_own(knob_on):
    """Both refused: two retries, and the third call carries neither."""
    c = _Client(refuse=("thinking", "temperature"))
    t._create_read(c, "claude-opus-5", _kw("claude-opus-5"))
    assert len(c.calls) == 3
    assert "thinking" not in c.calls[-1] and "temperature" not in c.calls[-1]
    assert "claude-opus-5" in t._NO_TEMPERATURE
    assert "claude-opus-5" in t._NO_THINKING_OFF


def test_anything_else_still_surfaces(knob_on):
    class Dead(_Client):
        def create(self, **kw):
            raise RuntimeError("401 invalid x-api-key")
    with pytest.raises(RuntimeError, match="401"):
        t._create_read(Dead(), "claude-opus-5", _kw("claude-opus-5"))


def test_with_the_list_empty_a_read_on_opus_thinks_and_asks_nothing():
    """Today's setting. No `thinking` key on the wire - the model's own
    default (adaptive thinking) is what the comparison chose."""
    c = _Client()
    t._create_read(c, "claude-opus-5", _kw("claude-opus-5"))
    assert "thinking" not in c.calls[0]
    assert c.calls[0]["temperature"] == 0


def test_the_vision_path_goes_through_it():
    src = open(t.__file__, encoding="utf8").read()
    body = src.split("def _ask_vision(")[1].split("\ndef ")[0]
    assert "_create_read(client, model, kwargs)" in body
    assert "messages.create" not in body, \
        "a second call site is a second place to forget the knob"


# ------------------------------------------------------------- the two regimes

def _opus_read(think_off, tout):
    coins.note("ocr cost", "58 pages", "claude-opus-5", step="ocr",
               backend="anthropic", boxes=144, pages=58, tin=164_114,
               cached=94_335, tout=tout, calls=58, coins=1, charged=1,
               src=1757, detail="boxes",
               **({"think_off": True} if think_off else {}))


def test_a_thinking_run_does_not_vote_on_a_non_thinking_quote(knob_on):
    """lee's ledger holds the 19,576-token thinking read. Left to vote, it
    reads as the non-thinking shape overrunning 5x, clamps at 2.5, and the
    next eight quotes are two and a half times the bill."""
    _opus_read(think_off=False, tout=19_576)
    assert coins.drift("ocr", "claude-opus-5", "anthropic") == (1.0, 1.0, 1.0)


def test_a_non_thinking_run_does_vote(knob_on):
    _opus_read(think_off=True, tout=3_600 * 2)
    _din, dout, _ = coins.drift("ocr", "claude-opus-5", "anthropic")
    assert dout > 1.5, dout


def test_the_receipt_line_says_which_regime_it_was():
    from where import PKG
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    assert "think_off=(step == \"ocr\"" in src
    assert "coins.read_thinks_off(model)" in src


def test_a_non_thinking_run_does_not_vote_on_a_thinking_quote():
    """The other way round, which is today's case: lee's 190-coin
    non-thinking read is in the ledger, and the thinking quote must not
    read it as the thinking shape coming in at a fifth."""
    _opus_read(think_off=True, tout=3_600)
    assert coins.drift("ocr", "claude-opus-5", "anthropic") == (1.0, 1.0, 1.0)


def test_a_fresh_non_thinking_quote_is_the_visible_reply_alone(knob_on):
    """Lee's chapter as it was quoted for the comparison run. No reasoning
    in it, and therefore well under the 274 the thinking read cost - it
    came in at 190 - and the hold still covers a reply twice the predicted
    size."""
    boxes = [2, 2, 1, 2, 1, 1, 3, 2, 2, 3, 2, 2, 1, 2, 5, 4, 3, 1, 6, 3, 1, 3,
             3, 4, 2, 1, 4, 3, 2, 3, 2, 2, 0, 4, 4, 2, 5, 1, 2, 2, 1, 3, 4, 2,
             6, 4, 2, 2, 1, 3, 3, 3, 2, 3, 4, 0, 1, 1]
    srcs = [33, 17, 3, 4, 0, 2, 40, 28, 29, 23, 18, 24, 21, 27, 76, 33, 14,
            13, 70, 29, 18, 35, 25, 69, 62, 12, 80, 62, 24, 84, 60, 43, 0, 11,
            4, 15, 43, 10, 25, 37, 25, 37, 59, 48, 62, 73, 27, 12, 5, 4, 24,
            37, 20, 32, 66, 0, 2, 2]
    q = coins.quote("ocr", boxes, "claude-opus-5", "anthropic", 0, srcs,
                    ("manhwa", "en", "ko", True), "boxes")
    assert 150 <= q < 274, q
