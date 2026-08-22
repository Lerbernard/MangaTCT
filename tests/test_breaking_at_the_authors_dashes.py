"""A balloon too narrow for its words breaks where the author already broke it.

lee, with eight before-and-afters - GLOW-SAN! set as GLOW- / SAN!, LOOK
CLOSELY... set as LOOK / CLOSELY / ... :

> *can you make it so that when there isnst enoghth space to have teh minimuin
> text size, the tyoseeter can create new line where ther are already dahses or
> ...., it shoud create them just create a new line linke in teh picture as
> long as it donte exeet the box in height*

This is NOT hyphenation, which lee tried and hated and which this project has
refused everywhere else. Hyphenation invents a hyphen and puts it where a
dictionary says a word may be cut. This adds nothing at all: it breaks only
where the text already has a dash or a row of dots, and if there is no dash
and no row of dots it does nothing.

It only runs when the ordinary fit has already failed at `min_font` - that is
the condition lee named, and it is what keeps the rule from quietly reshaping
balloons that were fine.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.models import TextRegion
from mangatl.typeset import (TypesetConfig, author_break_tokens, author_breaks,
                             default_font_path, fit_region,
                             rejoin_author_breaks)


def _cfg(min_font=12, max_font=30):
    return TypesetConfig(font_path=default_font_path(),
                         min_font=min_font, max_font=max_font)


def _balloon(text, w, h):
    """One oval, one block, sized so the words do not fit at the minimum."""
    W, H = w + 60, h + 60
    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (W // 2, H // 2), (w // 2, h // 2), 0, 0, 360, 255, -1)
    r = TextRegion(id=1, bbox=(30, 30, w, h), kind="bubble", text_mask=m,
                   bubble_mask=m, bubble_bbox=(0, 0, W, H))
    r.dst_text = text
    return r


def _both(text, w, h, cfg=None):
    """(without the pass, with it) - layout and flag for each."""
    from mangatl import typeset as T
    cfg = cfg or _cfg()
    r = _balloon(text, w, h)
    was = T._fit_on_author_breaks
    T._fit_on_author_breaks = lambda *a, **k: None
    try:
        r.flagged = None
        off = (fit_region(r, cfg), r.flagged)
    finally:
        T._fit_on_author_breaks = was
    r = _balloon(text, w, h)
    r.flagged = None
    on = (fit_region(r, cfg), r.flagged)
    return off, on


# ------------------------------------------------- where a word may be cut

def test_a_dash_keeps_the_piece_before_it():
    """GLOW- / SAN!, the way lee's picture sets it. A line ending in a bare
    GLOW is a different word; the dash is what says the word continues."""
    assert author_breaks("GLOW-SAN!") == ["GLOW-", "SAN!"]
    assert author_breaks("SELF-CONTROL") == ["SELF-", "CONTROL"]
    assert author_breaks("A--B") == ["A--", "B"]


def test_a_row_of_dots_keeps_the_piece_after_it():
    """CLOSELY / ..., the way lee's picture sets it. The dots are the pause,
    and the pause hangs with what follows, not with what it trails from."""
    assert author_breaks("CLOSELY...") == ["CLOSELY", "..."]
    assert author_breaks("RECOVERY...?") == ["RECOVERY", "...?"]
    assert author_breaks("HUH!?...") == ["HUH!?", "..."]
    assert author_breaks("OK…") == ["OK", "…"]


def test_a_break_needs_something_on_both_sides():
    """A trailing dash is how a line ends and a leading one is an interrupted
    speaker. Cutting at either would leave a dash standing alone on a line of
    its own, which is the one thing a dash must never do. Same for an
    ellipsis that opens a sentence - it belongs to the words it introduces."""
    assert author_breaks("WHAT—") == ["WHAT—"]
    assert author_breaks("—WELL") == ["—WELL"]
    assert author_breaks("...GLOW") == ["...GLOW"]
    assert author_breaks("…SOON") == ["…SOON"]


def test_a_full_stop_is_a_full_stop():
    """One dot ends a sentence; two or more are a pause. Breaking at every
    full stop would put the next sentence on a new line in every caption."""
    assert author_breaks("Mr.") == ["Mr."]
    assert author_breaks("NOW.HERE") == ["NOW.HERE"]
    assert author_breaks("plain") == ["plain"]
    assert author_breaks("") == []


def test_pieces_that_are_not_broken_go_back_together():
    """The fitter is handed the pieces spaced apart so it MAY break between
    them. Two pieces that land on one line are one word again - GLOW- SAN!
    with a space in it is not a word anybody wrote."""
    toks, glue = author_break_tokens("GLOW-SAN!")
    assert (toks, glue) == (["GLOW-", "SAN!"], [False, True])
    assert rejoin_author_breaks(["GLOW- SAN!"], toks, glue) == ["GLOW-SAN!"]
    assert rejoin_author_breaks(["GLOW-", "SAN!"], toks, glue) == ["GLOW-",
                                                                   "SAN!"]
    # …and a space the author wrote is still a space.
    toks, glue = author_break_tokens("LOOK CLOSELY...")
    assert toks == ["LOOK", "CLOSELY", "..."]
    assert glue == [False, False, True]
    assert rejoin_author_breaks(["LOOK CLOSELY ..."], toks, glue) == \
        ["LOOK CLOSELY..."]


def test_lines_that_are_not_the_sequence_handed_out_are_left_alone():
    """A guard, not a behaviour. If the fitter ever returns something other
    than these tokens in this order, the rejoin must hand the lines back
    untouched rather than build a sentence out of the wrong pieces."""
    toks, glue = author_break_tokens("GLOW-SAN!")
    assert rejoin_author_breaks(["GLOW- SAN! EXTRA"], toks, glue) == \
        ["GLOW- SAN! EXTRA"]
    assert rejoin_author_breaks(["GLOW-"], toks, glue) == ["GLOW-"]
    # The one that bites: the right NUMBER of words, drawn from the wrong end
    # of the sequence. Rebuilding from the pieces in hand would silently
    # rewrite the line - LOOK would appear in a line that never had it.
    toks, glue = author_break_tokens("LOOK CLOSELY...")
    assert rejoin_author_breaks(["CLOSELY ..."], toks, glue) == ["CLOSELY ..."]


def test_putting_a_pair_back_together_never_widens_the_line():
    """Why the origins from the spaced-out fit can be kept as they are.

    The fitter measured lines with a space between the pieces; the rejoined
    line has that space taken out, so it is narrower, so a layout that fitted
    still fits and a line that was centred is still centred on the same
    point. If a font ever made a rejoin WIDER - a kerning pair that opens up
    where a space closes - that reasoning breaks and this says so."""
    from mangatl.typeset import _font
    f = _font(default_font_path(), 14)
    for spaced, joined in [("FACT ...", "FACT..."), ("GLOW- SAN!", "GLOW-SAN!"),
                           ("SELF- CONTROL", "SELF-CONTROL"),
                           ("RECOVERY ...?", "RECOVERY...?"), ("OK …", "OK…")]:
        assert f.getlength(joined) <= f.getlength(spaced), (spaced, joined)


def test_nothing_to_break_at_costs_nothing():
    """The fit is the expensive thing on the page - it walks every size and
    every leading. A text with no dash and no dot run has nothing this pass
    can do, and must not pay for a second identical walk to find that out.

    Asked of THIS pass rather than counted across a whole `fit_region`. It
    used to be counted: one call for a plain text, two for one with a dash in
    it. That was true when this was the only thing standing behind the
    ordinary fit, and stopped being true the day a second fallback joined it
    - a text with nothing to break at now walks on to the narrower fit, which
    is its own walk and its own question. The claim here is unchanged; only
    the way of asking it had to stop depending on what else exists."""
    from mangatl import typeset as T
    calls = []
    real = T._best
    T._best = lambda *a, **k: (calls.append(a[0]), real(*a, **k))[1]
    try:
        cfg = _cfg()
        plain = _balloon("ABSOLUTELY UNBREAKABLE PRONOUNCEMENT", 70, 90)
        assert T._fit_on_author_breaks(
            plain.dst_text, plain.place_mask(), cfg) is None
        assert not calls, "nothing to break at, so nothing was fitted again"

        broken = _balloon("LOOK CLOSELY...", 82, 104)
        T._fit_on_author_breaks(broken.dst_text, broken.place_mask(), cfg)
        assert len(calls) == 1, "one more walk, and only where there is a break"
    finally:
        T._best = real


# ------------------------------------------------------ what lee looked at

CASES = [
    ("GLOW-SAN!", 76, 96, ["GLOW-", "SAN!"]),
    ("WHERE HAVE THEY COME FOR ADA'S RECOVERY...?", 108, 150,
     ["WHERE", "HAVE", "THEY COME", "FOR ADA'S", "RECOVERY", "...?"]),
    ("YOU'RE BLEEDING...", 92, 110, ["YOU'RE", "BLEEDING", "..."]),
    ("LOOK CLOSELY...", 82, 104, ["LOOK", "CLOSELY", "..."]),
]


@pytest.mark.parametrize("text,w,h,want", CASES)
def test_lees_four_examples_are_set_the_way_he_set_them(text, w, h, want):
    (a, fa), (b, fb) = _both(text, w, h)
    assert a.lines != want, "the balloon already broke here; fixture too easy"
    assert b.lines == want, b.lines
    # Bigger, not smaller - the whole reason to break at all.
    assert b.font_size > a.font_size, (a.font_size, b.font_size)
    # …and above the minimum.
    assert b.font_size >= _cfg().min_font, b.font_size
    # Without this pass the block came out of `_plain_fit`, which wraps into
    # the bounding RECTANGLE and says so by reporting `fit_ok=False` - the
    # corners of a rectangle drawn round a balloon are not inside the balloon.
    # With it, the words are fitted to the SHAPE.
    #
    # It used to be the overflow flag that was read here, because the plain
    # wrap was the shrink-below-the-minimum path and nothing else. It still
    # is, but it now breaks at the author's dashes as well (lee: *"all box
    # type shoud do the line break thing wjhen the text is too small"*), so it
    # reaches the minimum without shrinking and no longer flags. What this
    # pass is FOR was never the flag; it is the balloon fit.
    assert not a.fit_ok, "the fixture did not need this pass at all"
    assert b.fit_ok, "still not a fit to the balloon's own shape"
    assert not fb, fb


def test_a_pair_the_fitter_did_not_break_is_drawn_as_one_word():
    """The four cases above all break at every piece, so they never exercise
    the rejoin on a real page. This one does: the balloon needs the dash
    break, does not need the dot break, and HARD... must come out as one word
    and not as HARD followed by a space and an ellipsis.

    Whether that space is there is not a detail - a gap before the dots is
    the difference between a pause and a typo, and it would be in the export
    and on the page."""
    (a, fa), (b, fb) = _both("SELF-CONTROL IS HARD...", 88, 140)
    assert not a.fit_ok, "it did not need the pass"  # it needed the pass...
    assert b.lines == ["SELF-", "CONTROL", "IS", "HARD..."], b.lines
    assert not fb, fb
    for ln in b.lines:
        assert " ." not in ln, ln
        assert " …" not in ln, ln
        assert "- " not in ln, ln
        assert ln == ln.strip(), ln


@pytest.mark.parametrize("text,w,h,want", CASES)
def test_every_word_still_goes_in_whole(text, w, h, want):
    """Nothing is dropped and nothing is invented: run the lines together and
    you have the sentence, character for character.

    Not `" ".join(lines).split() == text.split()` - that is the check for the
    ordinary fitter, where every break is a space. Here a break can fall
    inside a word, so the words on the page are not the words in the
    sentence. What must hold is the characters, in order, once the whitespace
    the breaks stand in for is taken out of both sides."""
    _off, (b, _fb) = _both(text, w, h)
    flat = "".join(b.lines).replace(" ", "")
    assert flat == text.replace(" ", ""), b.lines
    assert len(flat) == len(text.replace(" ", ""))      # nothing added either


@pytest.mark.parametrize("text,w,h,want", CASES)
def test_it_stays_inside_the_box(text, w, h, want):
    """lee: *"as long as it donte exeet the box in height"*. More lines is the
    price of the bigger type, and it must not be paid by running out of the
    balloon top or bottom."""
    from mangatl.typeset import _font
    _off, (b, _fb) = _both(text, w, h)
    top = min(y for _x, y in b.line_origins)
    bot = max(y for _x, y in b.line_origins) + b.font_size * b.leading
    assert top >= 30 - 4, top                       # the box starts at y=30
    assert bot <= 30 + h + 4, (bot, 30 + h)
    f = _font(b.font_path, b.font_size)
    for ln, (x, _y) in zip(b.lines, b.line_origins):
        half = f.getlength(ln) / 2.0
        assert x - half >= 30 - 4, (ln, x - half)
        assert x + half <= 30 + w + 4, (ln, x + half)


# ------------------------------------------------------- and when it must not

def test_a_balloon_that_already_fits_is_not_touched():
    """The pass runs only when the ordinary fit found nothing at `min_font` or
    above. A roomy balloon must typeset exactly as it did - otherwise this is
    not a fallback, it is a change to how every page is set."""
    for text, w, h, _want in CASES:
        (a, fa), (b, fb) = _both(text, w + 130, h + 130)
        assert not fa, (text, fa)               # it fitted without the pass...
        assert b.lines == a.lines, (text, a.lines, b.lines)
        assert b.font_size == a.font_size, text
        assert b.line_origins == a.line_origins, text
        assert not fb, fb


def test_text_with_no_dash_and_no_dots_is_unchanged():
    """Nothing to break at, so nothing happens - including the flag, which
    still says what it always said."""
    text = "ABSOLUTELY UNBREAKABLE PRONOUNCEMENT"
    (a, fa), (b, fb) = _both(text, 70, 90)
    assert a.lines == b.lines, (a.lines, b.lines)
    assert a.font_size == b.font_size
    assert fa == fb
    assert fa and "overflow" in fa, fa


def test_a_word_is_still_never_split():
    """The standing rule, restated where it could most easily be broken. One
    long word with no dash in it goes under the minimum and is flagged, as it
    always has been - no hyphen appears anywhere."""
    (a, fa), (b, fb) = _both("SUPERCALIFRAGILISTIC", 64, 90)
    assert b.lines == a.lines == ["SUPERCALIFRAGILISTIC"], (a.lines, b.lines)
    assert "-" not in "".join(b.lines)
    assert fb and "overflow" in fb, fb


# --------------------------------------- and in the path that shrinks as well

def _tight(text, w, h):
    """A rectangular box, so the only fit left is the plain rectangular wrap.

    An oval is the wrong shape for this: `_best` measures against the balloon's
    own chords and `_plain_fit` against the bounding rectangle, so a fixture
    that is round leaves a gap between them big enough to hide what is being
    asked. Here the two see the same box and the only difference left is the
    one under test - where the wrap is allowed to break.
    """
    W, H = w + 60, h + 60
    m = np.zeros((H, W), np.uint8)
    m[30:30 + h, 30:30 + w] = 255
    r = TextRegion(id=1, bbox=(30, 30, w, h), kind="bubble", text_mask=m,
                   bubble_mask=m, bubble_bbox=(0, 0, W, H))
    r.dst_text = text
    r.flagged = None
    return r, m


def _with_and_without_breaks(text, w, h):
    """(spaces only, the author's breaks too) for the last-resort wrap."""
    from mangatl import typeset as T
    cfg = _cfg()
    real = T.author_break_tokens
    r, m = _tight(text, w, h)
    # Spaces only is what this path did before: hand it back the words.
    T.author_break_tokens = lambda t: (t.split(), [False] * len(t.split()))
    try:
        off = (fit_region(r, cfg, mask=m), r.flagged)
    finally:
        T.author_break_tokens = real
    r, m = _tight(text, w, h)
    return off, (fit_region(r, cfg, mask=m), r.flagged)


def test_the_last_resort_breaks_at_the_dash_rather_than_shrink_under_it():
    """lee, with GLOW-SAN! at 7pt and an overflow warning next to it: *"all box
    type shoud do the line break thing wjhen the text is too small"*.

    Every path above this one already broke at the author's dashes before it
    shrank anything. This one - the only one that goes UNDER the legibility
    floor - did not, so a box with room for GLOW- over SAN! at the minimum got
    one illegible line instead. It is one word: there is no space in it, so
    wrapping on spaces could never do anything but shrink."""
    (a, fa), (b, fb) = _with_and_without_breaks("GLOW-SAN!", 55, 60)
    assert a.lines == ["GLOW-SAN!"], a.lines
    assert a.font_size < _cfg().min_font, a.font_size
    assert fa and "shrunk below the minimum" in fa, fa

    assert b.lines == ["GLOW-", "SAN!"], b.lines
    assert b.font_size >= _cfg().min_font, b.font_size
    assert b.font_size > a.font_size, (a.font_size, b.font_size)
    assert not fb, fb


def test_the_last_resort_rejoins_a_pair_it_did_not_break():
    """The pieces are measured spaced apart so the wrap may break between
    them; two that land on one line are one word again. A gap before the dots
    is the difference between a pause and a typo, and it would go out in the
    export."""
    (_a, _fa), (b, _fb) = _with_and_without_breaks("SELF-CONTROL...", 56, 90)
    assert b.lines == ["SELF-", "CONTROL", "..."], b.lines
    assert "".join(b.lines) == "SELF-CONTROL...", b.lines
    for ln in b.lines:
        assert " ." not in ln and " …" not in ln, ln
        assert "- " not in ln, ln
        assert ln == ln.strip(), ln


def test_a_word_with_nothing_to_break_at_still_is_not_split():
    """The standing rule, in the one path that has the most reason to break
    it: the alternative here is genuinely illegible type."""
    r, m = _tight("SUPERCALIFRAGILISTIC", 64, 60)
    lay = fit_region(r, _cfg(), mask=m)
    assert lay.lines == ["SUPERCALIFRAGILISTIC"], lay.lines
    assert "-" not in "".join(lay.lines)
    assert r.flagged and "overflow" in r.flagged, r.flagged


def test_a_plain_sentence_wraps_exactly_as_it_did():
    """No dash and no dot run, so the tokens ARE the words and this path must
    be unchanged, down to where the lines break and where they sit."""
    (a, _fa), (b, _fb) = _with_and_without_breaks(
        "A BIG LONG SENTENCE HERE", 60, 60)
    assert b.lines == a.lines, (a.lines, b.lines)
    assert b.font_size == a.font_size
    assert b.line_origins == a.line_origins


def test_the_warning_only_says_shrunk_when_it_shrank():
    """A red bar on a page that is perfectly well typeset teaches people to
    stop reading the red bars. This path used to flag every layout it
    returned, including the ones that came back AT the minimum size, and the
    message named a shrink that had not happened."""
    r, m = _tight("GLOW-SAN!", 55, 60)
    lay = fit_region(r, _cfg(), mask=m)
    assert lay.font_size == _cfg().min_font, lay.font_size
    assert not lay.fit_ok, "the fixture stopped exercising the plain wrap"
    assert r.flagged is None, r.flagged

    # ...and it still says so when it really does go under.
    r, m = _tight("SELF-CONTROL...", 56, 90)
    lay = fit_region(r, _cfg(), mask=m)
    assert lay.font_size < _cfg().min_font, lay.font_size
    assert r.flagged and "shrunk below the minimum" in r.flagged, r.flagged
