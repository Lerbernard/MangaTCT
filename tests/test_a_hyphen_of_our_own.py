"""Breaking a word we were not given permission to break.

lee sent the published English chapter 22 as an example of *"how proper
tysetting is doen"*, and the thing on those pages that our fitter would never
do is split an ordinary word: `IDLE TRANS-/FIGURA-/TION`, `AN ORDINARY PERSON
EVENTUALLY DIES AFTER BEING TRANS-/FIGURED.` We set the word whole and small in
an empty balloon instead, which is how a block ends up covering 8% of its own
bubble.

Then: *"try this but i dont wanta buch of hypers everywhere"*.

That is a rate, so it was measured rather than guessed - and over FOUR
published chapters, not one, because one chapter is the work of one person:

    Jujutsu Kaisen 22        7 of 302     2.3 per 100 lines
    chapter 141             12 of 486     2.5
    My Hero Academia 425     6 of 448     1.3
    My Hero Academia 420     3 of 360     0.8
    ------------------------------------------------
    pooled                  28 of 1596    1.8

They disagree by a factor of three, so there is no single right answer, only a
range. `HYPHEN_GAIN = 1.30` puts lee's 23 pages at 1.8 per 100 - the pooled
figure. The tables are in `typeset.py`; the scripts are `his/hyph.py` and
`his/rate.py`.

Four brakes rather than one threshold doing all the work:

    HYPHEN_MIN_WORD  8   short words are never broken
    HYPHEN_MIN_HEAD  3   the pattern file allows 2, and two letters and a dash
    HYPHEN_MIN_TAIL  3   is a stub rather than a syllable
    HYPHEN_MAX       1   broken words in one block

and one offer per word, nearest the middle, because every extra place a line
COULD end in a hyphen is another line that does.

Where the breaks come from is `hyphen.py`: Liang's patterns, the English set
that has been in TeX since 1983, vendored from pyphen (GPLv2+/LGPLv2+/MPL,
compatible with this app's GPL-3.0) rather than depended on - an editor
somebody runs on their own machine should not need a package index to break a
word.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import hyphen as HY
from mangatl import typeset as T
from mangatl.models import TextRegion

H, W = 400, 400
TALL = dict(cx=200, cy=200, rx=51, ry=107)      # 102 x 214, like lee's page 017


def _oval(cx, cy, rx, ry):
    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (cx, cy), (rx, ry), 0, 0, 360, 255, -1)
    return m


def _cfg():
    return T.TypesetConfig(font_path=T.default_font_path(),
                           min_font=11, max_font=40)


def _fit(text, **oval):
    m = _oval(**(oval or TALL))
    r = TextRegion(id=0, bbox=(150, 95, 100, 210), text_mask=None,
                   bubble_mask=m, bubble_bbox=(150, 95, 100, 210),
                   kind="bubble")
    r.order, r.dst_text = 0, text
    return T.fit_region(r, _cfg(), m)


# ------------------------------------------------------- where English breaks

def test_the_patterns_break_words_where_english_does():
    """Liang's patterns, loaded and applied. `trans-figured` is the one on
    lee's reference page, which is the point of checking it."""
    def at(w):
        return {w[:p] + "-" + w[p:] for p in HY.points(w)}
    assert "trans-figured" in at("transfigured"), at("transfigured")
    assert "sor-cerer" in at("sorcerer"), at("sorcerer")
    assert "com-puter" in at("computer"), at("computer")
    assert at("manga") == set(), at("manga")


def test_a_word_too_short_to_break_is_not_offered_one():
    assert HY.points("table")           # English allows ta-ble...
    assert T.hyphen_points("table") == []      # ...and we do not offer it
    assert len("table") < T.HYPHEN_MIN_WORD


def test_no_stub_is_ever_left_on_either_side():
    """The pattern file's own minimum is two. Two letters and a dash reads as a
    typo, so ours is three at both ends - checked over a real vocabulary rather
    than one word."""
    words = ["unbelievable", "transfigured", "extraordinary", "information",
             "eventually", "sorcerer", "ordinary", "hyphenation", "beautiful",
             "photograph", "immediately", "everything", "understand"]
    for w in words:
        for p in T.hyphen_points(w):
            assert p >= T.HYPHEN_MIN_HEAD, (w, p)
            assert len(w) - p >= T.HYPHEN_MIN_TAIL, (w, p)


def test_one_place_per_word_and_it_is_the_middle_one():
    """English allows `un-believable`, `unbe-lievable` and `unbeliev-able`.
    Offering all three gives the fitter three chances to end a line in a
    hyphen, which is the page lee asked not to have."""
    got = T.hyphen_points("unbelievable")
    assert len(got) == 1, got
    assert len(HY.points("unbelievable")) > 1, "the fixture proves nothing"
    assert abs(got[0] - len("unbelievable") / 2.0) <= 2, got


# ------------------------------------------------------------ and in a balloon

def test_the_word_that_was_its_own_ceiling_now_breaks():
    """The case the whole thing is for: one long word in a tall narrow balloon,
    where that word's width is the entire ceiling."""
    lay = _fit("Unbelievable")
    assert len(lay.lines) == 2, lay.lines
    assert lay.lines[0].endswith("-"), lay.lines
    assert "".join(lay.lines).replace("-", "") == "Unbelievable", lay.lines


def test_and_it_is_bigger_for_it():
    lay = _fit("Unbelievable")
    whole = T._best("Unbelievable", _oval(**TALL) > 0, _cfg())
    assert lay.font_size >= T.HYPHEN_GAIN * whole.font_size, \
        (lay.font_size, whole.font_size)


def test_a_balloon_with_room_to_spare_keeps_the_word_whole():
    """The brake. A break that buys nothing is a mark nobody asked for.

    "Room to spare" has to mean room the break cannot use, and my first
    fixture did not: a balloon 300 wide and 220 tall broke `Unbe-/lievable`
    and was RIGHT to, because a single word cannot be wrapped any other way
    and two lines really do set bigger there. A wide oval is not a
    counter-example, it is the case working.

    So the fixture is a balloon where the whole word is already at `max_font`
    and there is nothing left for a break to win.
    """
    lay = _fit("Unbelievable", cx=200, cy=200, rx=190, ry=170)
    assert lay.lines == ["Unbelievable"], lay.lines
    assert lay.font_size == _cfg().max_font, lay.font_size


def test_and_a_sentence_that_can_simply_wrap_is_never_broken():
    """The common case by far, and the one that decides whether a page is
    covered in hyphens: ordinary dialogue with spaces in it wraps at the
    spaces, and no word is touched."""
    lay = _fit("An ordinary person eventually dies",
               cx=200, cy=200, rx=170, ry=150)
    assert not any(l.endswith("-") for l in lay.lines), lay.lines
    assert " ".join(lay.lines) == "An ordinary person eventually dies", \
        lay.lines


def test_the_author_s_own_dash_is_preferred_to_one_of_ours():
    """A dash already in the text costs the reader nothing; a hyphen we
    invented is a mark that was not there. So when both would serve, the
    author's wins - which is why `_fit_on_hyphens` is tried second."""
    lay = _fit("Double...?!")
    assert "".join(lay.lines) == "Double...?!", lay.lines
    assert not any(l.endswith("-") for l in lay.lines), lay.lines


def test_no_block_gets_more_than_one_broken_word():
    """`HYPHEN_MAX`. A balloon with three hyphens down its right edge is
    exactly what lee asked not to have, and the layout is refused outright
    rather than trimmed - a rule that is enforced is a rule you can rely on."""
    assert T.HYPHEN_MAX == 1
    lay = _fit("Unbelievable transfiguration extraordinary")
    assert sum(1 for l in lay.lines[:-1] if l.endswith("-")) <= T.HYPHEN_MAX, \
        lay.lines


def test_the_hyphen_is_measured_before_it_is_drawn():
    """The piece before a break carries its hyphen through the fit, so the
    fitter measures the WIDER thing; a pair that ends up on one line is
    rejoined with the hyphen taken back out and is therefore narrower than
    what was measured, never wider. That is what makes a fit that fitted still
    fit."""
    toks, glue = T.hyphen_tokens("Unbelievable")
    assert toks[0].endswith("-") and glue[1] is True, (toks, glue)
    assert T.rejoin_hyphens(["Unbe- lievable"], toks, glue) == \
        ["Unbelievable"], "the measured hyphen was left in the middle of a word"


# ----------------------------------------------------------------- the rate

def test_the_gain_is_the_one_that_was_measured():
    """1.30 puts lee's chapter at 1.8 broken lines per 100, which is the rate
    four published chapters have between them.

    It was briefly 1.10, which matched Jujutsu Kaisen 22 exactly - and that
    was one chapter by one hand. Reading three more put the range at 0.8 to
    2.5 and the
    pooled figure at 1.8, so matching the first chapter to the tenth had been
    fitting one person's habit. Written down because the sweep lives in a
    comment and a comment cannot fail.
    """
    assert T.HYPHEN_GAIN == 1.30, T.HYPHEN_GAIN
    assert (T.HYPHEN_MIN_WORD, T.HYPHEN_MIN_HEAD, T.HYPHEN_MIN_TAIL) == \
        (8, 3, 3)


def test_the_patterns_ship_with_the_app():
    """Vendored, not depended on. A break needs no package index and no
    network - which is the whole reason the file is in the tree."""
    import os
    assert os.path.exists(HY._DICT), HY._DICT
    assert HY._load(), "the pattern file loaded to nothing"
