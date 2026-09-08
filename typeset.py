"""Typesetting - the stage that decides whether output looks hand-typeset.

Two ideas do most of the work:

1. Fit against the bubble MASK, not its bounding box. The usable width for a
   line is the narrowest horizontal chord of the bubble across that line's
   vertical band. Inside an oval this produces the tapered short/wide/short
   shape real typesetters use, for free.

2. The full translation ALWAYS goes in. When it runs long the fitter breaks
   lines harder and drops the size - never swapping the wording, never
   splitting words, never letting text spill over the artwork.
"""
from __future__ import annotations

import copy
import math
import os
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Callable, Optional

import cv2
import numpy as np
from PIL import ImageFont

from .models import TextLayout, TextRegion
from . import kinds as _kinds
from . import marks as _marks


# ---------------------------------------------------------------- glyph safety
# Comic typesetting fonts cover surprisingly little beyond ASCII. Any character
# the chosen font has no glyph for renders as a tofu box (□) in the EXPORT -
# the editor preview is browser-rendered and quietly substitutes another font,
# which is why the boxes only ever show up at the end. The rule here is
# absolute: nothing reaches the page unless the font can draw it.

_NORMALIZE = {
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    # long dashes stay em-dashes now - the font list only offers faces that
    # can draw one, so it renders instead of turning to tofu
    "–": "—", "—": "—", "―": "—", "⸺": "—",
    "…": "...",
    " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", "　": " ",
    "〜": "~", "～": "~",     # 〜 and the fullwidth tilde
    "ー": "-",                     # ー chōonpu leaking from the source
    "！": "!", "？": "?", "，": ",", "．": ".",
    "：": ":", "；": ";",
    "‼": "!!", "⁉": "!?", "⁈": "?!", "⁇": "??",
    "×": "x", "−": "-", "•": "*", "□": "",
}
_STRIP = dict.fromkeys(map(ord, "​‌‍﻿­"))


def normalize_text(t: str) -> str:
    """Typographic characters to plain renderable equivalents; invisible
    characters out. Cheap, font-independent, safe to run on every write."""
    if not t:
        return t or ""
    t = unicodedata.normalize("NFC", t).translate(_STRIP)
    t = "".join(_NORMALIZE.get(c, c) for c in t)
    # A run of hyphens ("OH--RIGHT", a model following old double-hyphen
    # advice, or -- typed by hand) is one em-dash: "OH—RIGHT". A lone hyphen
    # is left alone, so "FIRST-STAGE" keeps its hyphen.
    t = re.sub(r"-{2,}", "—", t)
    return _unstar(t)


# Asterisks around a word are a CHAT convention for "this is an action or a
# sound", and models reach for them constantly on sound effects and on wordless
# bubbles - *TURN*, *pant* *pant*, *sniff*. No typesetter draws them. lee: *"make
# it so that sfx never have these * on the beginning and end"*.
#
# Only a matched PAIR comes off, and only with something between the two. That
# is what leaves a MASKED word alone: "f***" and "sh*t" have no pair wrapping
# text, so they come through exactly as they are. The app never censors - see
# `added_masking` in translate.py, and the rule about it in the prompt - but a
# page is allowed to mask its own word, and when it does, that mask is part of
# what the page says and has to survive the trip.
_STARRED = re.compile(r"\*([^*]+)\*")


def _unstar(t: str) -> str:
    # Twice round for "**TURN**", which is one pair inside another. The cap is
    # there because the loop is only allowed to run while it is shortening the
    # string, and a fixed small number says so plainly.
    for _ in range(4):
        stripped = _STARRED.sub(r"\1", t)
        if stripped == t:
            break
        t = stripped
    return t


_COVERAGE_CACHE: dict[str, "set[int] | None"] = {}


def _font_coverage(path: str):
    """Set of codepoints the font can draw, or None if unknowable."""
    if path in _COVERAGE_CACHE:
        return _COVERAGE_CACHE[path]
    cov = None
    try:
        from fontTools.ttLib import TTFont
        f = TTFont(path, fontNumber=0, lazy=True)
        cov = set(f.getBestCmap().keys())
        f.close()
    except Exception:
        cov = None            # no fontTools / odd font: static map still runs
    _COVERAGE_CACHE[path] = cov
    return cov


def font_supports(path: str, ch: str) -> bool:
    """Can this font draw `ch`? Unknowable coverage (no fontTools, odd file)
    counts as yes - better to keep a font we cannot inspect than to hide
    everything."""
    cov = _font_coverage(path)
    if cov is None:
        return True
    return ord(ch) in cov


def sanitize_for_font(t: str, font_path: str,
                     substitutes: bool = False) -> str:
    """The text, made drawable by this font - if it is allowed to be.

    With `substitutes` on, every uncovered character either maps to a covered
    stand-in, decomposes to a covered base letter (ō -> o), or is dropped
    outright: a missing character reads better than a tofu box.

    With it OFF - the default - the text comes back normalized and otherwise
    untouched. The face you chose is the face the words are set in, and a
    character it cannot draw is left there to be seen rather than quietly
    swapped for one it can. See `TypesetConfig.substitutes`.
    """
    # The whitespace tidy is not a substitution and happens either way - a
    # run of spaces and a stray one at the end are about the TEXT. Callers
    # rely on it: `layout_from_override` keeps a line's own indent and passes
    # the rest through here, so a version that left the leading spaces in
    # place would double them.
    tidy = lambda x: re.sub(r"[ \t]{2,}", " ", x).strip()
    t = normalize_text(t or "")
    cov = _font_coverage(font_path) if font_path and substitutes else None
    if not cov:
        return tidy(t)
    out = []
    for ch in t:
        # The em-dash is KEPT even when the font lacks the glyph - the
        # renderer draws it by hand (see em_dash_glyph). This is what lets a
        # comic font that ships only a hyphen still show a real long dash.
        # And so is every mark on the list (♥ ★ ♪ ⁉ …), for the same reason:
        # `mark_glyph` stamps them from the bundled mark faces, so they are
        # not tofu and are not this function's to drop. Dropping them here is
        # exactly how a ♥ picked from the special-characters dialog reached
        # the output text and then quietly vanished from the line the moment
        # the preview ran - lee: *"it dont add to either teh box or teh text
        # box"*.
        if ch == "\n" or ch == "—" or ch in MARK_CHARS or ord(ch) in cov:
            out.append(ch)
            continue
        rep = _NORMALIZE.get(ch)
        if rep is not None and all(ord(c) in cov for c in rep):
            out.append(rep)
            continue
        base = "".join(c for c in unicodedata.normalize("NFKD", ch)
                       if not unicodedata.combining(c))
        if base and all(ord(c) in cov for c in base):
            out.append(base)
            continue
        # no glyph, no stand-in: drop it
    return tidy("".join(out))

INF = float("inf")

# Breaks after these are natural; breaks that strand these are not.
_GOOD_BREAK_AFTER = {",", ".", "!", "?", ";", ":", "—", "…"}
_BAD_BREAK_BEFORE = {"a", "an", "the", "of", "to", "in", "on", "at", "is", "it"}


MAX_LEADING = 1.20
"""The LOOSEST line gap the fitter may choose for itself.

It was a floor of the same number, and lee looked at his pages beside the
published English chapter and said it the other way round: *"the real line gap
number is somewhere between 1 - 1.10 and 1.20 tyhe max youu shoud use is
1.20"*.

MEASURED, with one ruler over both. 293 line gaps off the published chapter 22
pages, and the same measurement run over the app's own output - line pitch
divided by the height of the tall letters, which is a thing you can see rather
than a number in a font file:

    published chapter 22      1.31   (quartiles 1.08 and 1.44)
    the app at 1.34 em        2.00
    the app at 1.20 em        1.80   <- the old FLOOR was here
    the app at 1.00 em        1.50
    the app at 0.90 em        1.35

The app's tightest automatic answer was 38% looser than the published median.
He was not describing a preference; the pages really were spaced apart."""

MIN_LEADING = 1.00
"""...and the tightest, which is where lee's range starts.

The old argument for a floor still holds and is why there is one at all: set
solid, ascenders and descenders interleave and a block stops looking like
lines of speech. The floor simply belongs at 1.00 rather than at 1.20, which
is where he put it.

Neither bound holds over a number typed into the panel. That is a person
deciding, and it stands however tight. The browser has both numbers in
panels.js and a test holds the two files together."""


# The gap that ACTUALLY MATTERS is the one you can see, and it is not the em
# multiple. A multiple of the type size means a different visible gap in every
# face, because faces put different amounts of their em into the letters:
#
#     Anton          tall letters are 0.87 of the em
#     ComicNeue      0.68
#     Gaegu          0.60
#
# The same 1.20 is airy on Gaegu and cramped on Anton - a 46% spread across
# the sixteen faces that ship. lee: *"also make sure your mesurement is good
# fro all fonts"*.
#
# So the sweep is written in TALL-LETTER HEIGHTS and converted per face. The
# numbers below are lee's range read on the default face, which is the face
# the range was named while looking at.
LEADING_REF = 0.68       # tall letters over the em, ComicNeue-Bold


def leading_for(path: str, want: float, size: int = 100) -> float:
    """`want` em on the default face -> the em multiple for THIS face.

    Same visible gap, whatever the letters are made of.

    The gap you SEE is the pitch less the letters: at leading L on a face
    whose tall letters are `asc` of the em, the white between two lines is
    `L - asc`. Holding that constant gives `L = want - REF + asc`, which is
    the same thing as scaling the whole pitch by `asc / REF` to within a
    rounding - a face with MORE of its em in the letters needs MORE em to
    leave the same white, not less. (I had this the wrong way up first, and
    the test that caught it is the one that asks whether the VISIBLE gap comes
    out the same on every face.)

    Clamped into lee's range at the end, so a very tall face cannot talk its
    way past the ceiling he set. On Anton the clamp binds: 0.87 of its em is
    letters, matching the reference white would want about 1.5, and it gets
    1.20. That is the ceiling doing its job rather than a rounding error.
    """
    try:
        f = _font(path or default_font_path(), size)
        box = f.getbbox("bdhklHT")
        asc = float(box[3] - box[1]) / float(size)
    except Exception:
        return float(want)
    if asc <= 0.01:
        return float(want)
    return max(MIN_LEADING, min(MAX_LEADING,
                                float(want) - LEADING_REF + asc))


@dataclass
class TypesetConfig:
    font_path: str = ""          # default, used when a kind has no font set
    # Each kind of text gets its own face: dialogue in a typesetting font,
    # sound effects usually in something heavier, narration often different again.
    fonts: dict = field(default_factory=dict)   # kind -> .ttf path
    max_font: int = 34
    min_font: int = 12          # hard floor; below this we flag for a human
    font_step: int = 1
    # Line gap, as a multiple of the type size, LOOSEST FIRST - the fitter
    # takes the first that fits. The ceiling is MAX_LEADING and the floor is
    # MIN_LEADING, and the whole band moved down when it was measured against
    # the published pages rather than guessed at: see MAX_LEADING for the
    # numbers and lee's *"the max youu shoud use is 1.20"*.
    #
    # These are read on the DEFAULT FACE. `leading_for` converts them for
    # whatever face a box is actually set in, so the gap you SEE is the same
    # one on all sixteen.
    #
    # The band is 1.00-1.10 and NOT 1.00-1.20, and the difference is the whole
    # of what lee said: *"the real line gap number is somewhere between 1 -
    # 1.10 and 1.20 tyhe max youu shoud use is 1.20"*. 1.20 is the most
    # anything may ever be, which is `MAX_LEADING` and what the panel will
    # take; the number the fitter actually reaches for is the first half of
    # that sentence. Put 1.20 in the sweep and it wins on every bubble with
    # room to spare, which is most of them - measured over four of his pages,
    # that landed the chapter at 1.75 against the published 1.31.
    leadings: tuple[float, ...] = (1.10, 1.06, 1.03, 1.00)
    max_lines: int = 9
    # Clearance between the typesetting and the bubble outline. A percentage of
    # the chord alone is not enough on its own: it gives a wide bubble plenty
    # of air and a narrow one almost none, and it knows nothing about the type
    # size, which is what the eye actually judges "too close to the edge"
    # against. So the gutter is the largest of three claims - a fraction of
    # the chord, a fraction of an em, and a hard pixel floor.
    # `margin` is a SECOND helping of clearance on top of the erosion below,
    # and it used to be 0.86 - a 221px balloon came out with 144px of usable
    # chord, and the typesetting shrank to match. The erosion already leaves the
    # gutter `gutters()` asks for, in every direction, so almost all of the
    # chord is usable; what is left here is the small extra pull-in that the
    # curve of a round bubble wants, and no more.
    margin: float = 0.92        # fraction of chord width usable
    pad_em: float = 0.34        # gutter as a fraction of the type size
    pad_px: int = 5             # gutter floor, in pixels
    v_margin_px: int = 4
    v_margin_frac: float = 0.05  # gutter as a fraction of bubble height
    uppercase: bool = False
    # May the typesetter stand something else in when the chosen face cannot
    # draw a character?
    #
    # OFF, which is the default, means the words are set in the face you
    # picked and in no other: no ō → o, no curly quote flattened to a straight
    # one to satisfy a font, and no falling through to another family when the
    # face has no lowercase. A character the font cannot draw is left in the
    # text and the region is flagged, so what you get is visible and fixable.
    #
    # ON restores the old behaviour, which exists because a symbol face or a
    # capitals-only face used to produce an empty balloon: a stand-in glyph,
    # or the whole line typeset in a spare, is better than nothing there.
    # lee: *"Fonts should only us that font no substitute, hve a use subtitute
    # button in the setting that if turned n will allow teh typeseeter to use
    # subtitute symeboxes, if its of the text the typesster shoud not use
    # them"*.
    substitutes: bool = False

    # Layout scoring. Taking the largest font that merely *fits* produces
    # nine cramped one-word lines; a typesetter would drop a size for balance.
    w_ragged: float = 0.80      # penalise unused width on each line
    w_small: float = 3.60       # penalise small type - readers notice this most
    w_orphan: float = 0.90      # penalise one-word lines that sit half empty
    # Penalise lines that differ in length from each other. This is the term
    # that reads the SHAPE of the block, and it is now one of the largest in
    # the model: raggedness alone is measured against each line's own chord,
    # and inside an oval that lets a stack of one-word stubs near the poles
    # score as tidy. Comparing the lines to one another is what sees it.
    w_balance: float = 3.20
    # A block that leaves most of its balloon empty - "ARE YOU ALL RIGHT?" as a
    # 16pt two-line ribbon in a bubble that takes it at 23 on four lines, or
    # "I'M SORRY." as a 19pt one-liner where 28 on two fits. `small` cannot see
    # this: it prices type against the size range and knows nothing about the
    # room around it.
    #
    # The penalty is a one-sided ramp (see `_candidates`), so this weight is
    # the price of a block that covers NONE of its balloon and it is paid on a
    # sliding scale up to `vfill_target`, above which it is zero. That is why
    # it is an order of magnitude larger than the terms beside it and still
    # contributes nothing to a typical layout.
    w_vfill: float = 10.0
    # The share of the balloon's usable height a block has to cover before it
    # stops looking stranded. A third is where lee's approved rows sit (the
    # thinnest, "THAT PRINCESS NEVER HAD ANY POWER...", covers 0.33) and where
    # the rejected one does not ("IT'S TRUE... SHE CAN'T USE HER HEALING POWER
    # ANYMORE, BUT-" covered 0.20 before this term existed). Raising it toward
    # a half starts pushing "SO. WE / NEED TO / TALK." into a five-stub column
    # to buy height it does not need.
    vfill_target: float = 0.30
    # How much the LAST line counts in the shape penalties. Prose lets it run
    # short for free; comic typesetting wants the block to look deliberate, so
    # it counts - just less than the lines above it.
    w_last_line: float = 0.45
    w_cpl: float = 3.80         # penalise deviation from comfortable line length
    ideal_cpl: int = 16         # characters per line a typesetter aims for
    absolute_floor: int = 7     # never typeset smaller than this, ever
    strict_containment: bool = True   # text may never leave its box
    # Penalise tall stacks of lines. It has to hold its own against `w_vfill`
    # and `w_small` above, which both reward buying a bigger size with another
    # line break: at 0.25 a six-line column of single words was cheap enough to
    # win. Raising it is what keeps "MY HARD / WORK PAID / OFF TOO-" three
    # lines instead of six.
    w_lines: float = 1.00
    soft_max_lines: int = 5     # a sentence rarely needs more than this
    # Past that floor, one more line is free for every this many characters of
    # translation, so a long speech can use the lines a long speech needs.
    relax_cpl: float = 10.5
    # ...and the balloon gets a say too. A count of characters knows nothing
    # about the SHAPE it is being poured into: in a tall narrow bubble many
    # short lines is not a stack, it is the shape doing what it was drawn to
    # do. This is the fraction of the rows the bubble's usable height affords
    # that a block may spend before anybody calls it a stack - discounted from
    # 1.0 because the top and bottom of a rounded bubble are too narrow to
    # typeset right across.
    rows_afforded: float = 0.70


# The balloon types a typesetter actually names, in the order the Comicraft
# glossary lists them. lee: *"Look for a manga translation guide to see what
# type of bubble i shoud use instad of speech bubble outide bubble etc"*.
#
# Every one of these except the last two is a BALLOON - round, scalloped,
# jagged or square, it is still a closed shape with a tail, so the geometry is
# identical and only the typesetting differs. `freefloat` is dialogue with no
# balloon around it at all (a typesetter calls this open typesetting), and `sfx` is
# a drawn sound, which answers to its own shape.
# The three families. What a box IS finer than this is a sub-type, which a
# person makes and names - see kinds.py. Nothing in the typesetter reads a
# sub-type directly: everything asks which family a box is in.
KINDS = _kinds.FAMILIES

# How big a type is allowed to get, against the page's own maximum.
#
# A burst is shouted, so it is set large. This raises the CEILING only: the
# fitter still shrinks to the shape, so a shout in a small balloon comes out
# exactly as it did, and it is permission rather than an instruction.
#
# Thought and caption are set at normal size and told apart by the FACE. That
# is what a sub-type's own font is for, and it is what a typesetter does too - an
# italic for thought.
#
# Keyed on the SUB-TYPE, not the family: it is a burst that is set large, and a
# burst is one kind of balloon among several. `shout` is the key the burst
# sub-type is seeded with, so a project that has kept it keeps this too.
KIND_SCALE = {"shout": 1.15}


def usable_font(path: str) -> bool:
    try:
        ImageFont.truetype(path, 16)
        return True
    except Exception:
        return False


_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def can_typeset(path: str) -> bool:
    """Whether a font can be TYPESET with, not merely opened.

    `usable_font` only says the file loads. A machine has plenty of fonts that
    load perfectly and contain no letters at all - icon sets, dingbats, symbol
    and emoji faces. Choosing one of those used to wipe the page: the text is
    made drawable by the chosen font before it is measured (sanitize_for_font
    drops what the font cannot draw), so against a face with no alphabet every
    word disappears and the bubble is laid out empty. Nothing said why.

    A font that cannot draw the alphabet is not a typesetting font, so it is
    refused at the point it is chosen instead. A handful of missing letters is
    tolerated - the test is "has an alphabet", not "is complete".
    """
    if not usable_font(path):
        return False
    cov = _font_coverage(path)
    if not cov:               # unreadable cmap: it is not ours to judge
        return True
    have = sum(1 for ch in _ALPHABET if ord(ch) in cov)
    return have >= 40         # of 52; a caps-only face still passes on A-Z


def keeps_the_words(raw: str, safe: str) -> bool:
    """Whether sanitising against a font left the line still readable.

    Under a font missing the letters, `sanitize_for_font` returns a stub - the
    punctuation, an em dash, nothing. That is not a line of dialogue any more,
    and laying it out is how a page ends up blank.
    """
    want = sum(1 for c in raw if c.isalnum())
    if not want:
        return True
    got = sum(1 for c in safe if c.isalnum())
    return got >= 0.8 * want


def shows_text(lay) -> bool:
    """Whether a layout would actually put something on the page."""
    return bool(lay is not None and lay.lines
                and any(s.strip() for s in lay.lines))


# What each kind is typeset in when nobody has said otherwise.
#
# Every one of these ships with the app, and every one is under the SIL Open
# Font License, which permits redistribution inside software. That is the whole
# reason the list looks like this rather than like a professional's: Comicraft's
# Wild Words and Blambot's Anime Ace are the faces this job actually wants, and
# neither may be bundled in a downloadable program at any price we can pay. See
# `fonts/LICENSES.md`.
#
# The choices follow professional practice where an open face can reach it:
#
#   speech      a comic face with a true italic and bold, so thoughts and
#               whispers are the SAME face rather than a different one
#   thought     the italic - what the professional pages use
#   whisper     the regular, lighter than the speech bold
#   aside       a handwriting face, as a mutter in the margin is hand-written
#   effects     a heavy display face; small ones a lighter hand
#
# EVERY kind has an entry, including the ones whose answer is the same as their
# family's. lee, looking at the Box Types panel with a row per kind: *"add a
# font for all of these, these are the default ones"*, and *"they dont all have
# to be difrent"*.
#
# Three of them were left to inherit at first, which was defensible in the code
# and wrong on the screen: a person reading a list of twelve rows wants twelve
# answers, and "this one is whatever the one above it is" is a thing the panel
# would have to explain. Repetition costs nothing and reads as a decision;
# blanks read as an oversight.
#
# `sfx_big` says Bangers, the same as `sfx`, for that reason. `sign` is the one
# real compromise: it wants a plain narrow sans, there is no plain narrow sans
# in this folder, and Comic Neue Regular is the most neutral face that is.
#
# `shout` said Comic Neue Bold at first, on the argument that a shout is the
# speech face set larger. lee, looking at it: *"use a more agressive forny for
# shouting"*, and set beside the alternatives he is right - the bold of a light
# comic face is the speech face a little darker, and nothing about it is loud.
# Luckiest Guy carries 1.8x the ink of it at the same size: thick strokes,
# tight counters, and effectively all-caps, which is how shouts are set anyway.
#
# Deliberately not Bangers: that is the SOUND EFFECT face, and a shout drawn in
# it stops reading as somebody speaking. Not Anton either - it measures denser
# still, but only because it is CONDENSED, less white in the box rather than
# more ink in the stroke, and a condensed grotesque reads as a headline dropped
# into a balloon rather than as a voice. Chewy is heavy and round, which comes
# out playful instead of angry. Both refusals are pinned by tests, the Anton one
# as advance width against cap height - see `test_only_what_we_may_ship.py`.
DEFAULT_FONTS = {
    # speech, and the sub-types that are the same voice at another volume
    "bubble":         "ComicNeue-Bold.ttf",
    "narration":      "ComicNeue-Regular.ttf",
    "thought":        "ComicNeue-Italic.ttf",
    # A FLASH balloon - speech drawn ornately, not an unvoiced thought.
    #
    # It took the thought face when the type was split off - lee: *"make it
    # have teh same fonts"* - and it takes the SPEECH face now, which is his
    # second answer and the one that follows from the first: he sent a picture
    # of the panel and said *"make thses teh defualts"*, and the Fancy bubble
    # row on it reads Comic Neue Regular.
    #
    # It is also the better answer. The italic was inherited from a type this
    # one had been wrongly filed under, and italic in a balloon means "not said
    # aloud" - which is the exact thing a fancy balloon is not. What makes it
    # fancy is drawn round the balloon by the artist, and the typesetting does
    # not need to say it a second time.
    "fancy":          "ComicNeue-Regular.ttf",
    # Luckiest Guy until 2026-08-28. lee: *"the shoudt we have bnow is too
    # agressive can yu find something in getween those too"* - between it and
    # Comic Neue Bold, which he named as the quiet end.
    #
    # Bangers, at his word: *"acculy use bangers tregulat for shout boxes"*,
    # after Jua and after seeing the whole folder set side by side. It sits in
    # the interval he asked for - 1.68 times the speech face's ink against
    # Luckiest Guy's 1.81 - and it is drawn rather than merely heavy.
    #
    # IT IS ALSO THE SOUND EFFECT FACE, and that is the cost, said out loud
    # here because it is the one thing this choice gives up: a shouted line
    # and a drawn sound are now typeset identically, so the only thing telling
    # a reader which is which is the burst drawn round the one of them. It was
    # his call with the cost in front of him, and a preference is not a defect.
    # `test_the_shout_face_is_the_sound_effect_face_on_purpose` holds the
    # record so nobody 'fixes' it later.
    "shout":          "Bangers-Regular.ttf",
    "whisper":        "ComicNeue-Regular.ttf",
    # ...text out on the artwork...
    "freefloat":      "ComicNeue-Regular.ttf",
    "narration_free": "ComicNeue-Regular.ttf",
    # Patrick Hand until 2026-08-28, on the reasoning that a mutter is a note
    # in the margin and wants a hand. lee, with the panel in front of him:
    # *"make thses teh defualts"*, and the Aside row on it reads Comic Neue
    # Regular - which is what an aside gets when nothing is chosen for it, and
    # what he has been looking at while judging the pages.
    #
    # Patrick Hand is still the first recommendation for this type on the
    # Fonts page; it is a face somebody chooses now rather than one that
    # arrives.
    "aside":          "ComicNeue-Regular.ttf",
    "sign":           "ComicNeue-Regular.ttf",
    # ...and the effects, which are display type
    "sfx":            "Bangers-Regular.ttf",
    "sfx_big":        "Bangers-Regular.ttf",
    "sfx_small":      "Kalam-Regular.ttf",
}


# Which family each sub-type BELONGS to, for the purpose of the defaults above.
#
# `kinds.family_of` answers this from the project's own sub-type settings, and
# a project that has never configured any - a new one, or lee's - has none to
# answer from, so every sub-type comes back "bubble". That is the right answer
# there (an unknown kind is a balloon, where being wrong costs least) and the
# wrong one here: it sent `sfx_big` to the speech face and `sign` with it.
#
# `kinds.PRELOADED` already declares the family of every sub-type the app ships
# with, so the defaults read that instead. Anything a person has added
# themselves is not in it and falls back to `family_of`, which is where their
# own configuration lives.
_PRELOAD_FAMILY = {key: fam
                   for fam, subs in (_kinds.PRELOADED or {}).items()
                   for key, _label in subs}


def _bundled(name: str) -> str:
    """A shipped face by file name, or "" if this install has not got it."""
    for d in _font_dirs():
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return ""


def font_for(cfg: "TypesetConfig", kind: str, override: str = "") -> str:
    """This box's own font, then its sub-type's, then its FAMILY's, then the
    default.

    The family step is the one that matters now there are sub-types: a thought
    balloon with no face of its own is still a balloon, and should be typeset
    in the balloon face rather than dropping all the way through to the
    project default - which on a page of sound effects is a different face
    again.

    `DEFAULT_FONTS` sits AFTER the project's own font and not before it: a
    person who chose one face for their whole project chose it for the sound
    effects too, and having the app quietly overrule that would be worse than
    a plain default. It is reached when a project names nothing - a new one -
    and when what it names has gone, which is what happens to a setting
    pointing at a font this app used to ship and no longer may.
    """
    fam = _kinds.family_of(kind or "")
    fonts = cfg.fonts or {}
    for want in (override, fonts.get(kind),
                 fonts.get(fam) if fam != kind else None,
                 cfg.font_path,
                 _bundled(DEFAULT_FONTS.get(kind, "")),
                 _bundled(DEFAULT_FONTS.get(
                     _PRELOAD_FAMILY.get(kind, fam), ""))):
        if want and usable_font(want):
            return want
    # Never a path that cannot be opened: a dead string here is a block that
    # renders as nothing at all, which is the one outcome worse than the wrong
    # face.
    return cfg.font_path if usable_font(cfg.font_path) else default_font_path()


@lru_cache(maxsize=1)
def _font_dirs() -> tuple:
    """Where the bundled faces live, wherever the editor was started from.

    Resolved against THIS file first. Looking only at the working directory is
    how an install with a full fonts/ folder still said "No usable font": the
    editor is launched from wherever the user happens to be standing.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    out = []
    from .userdata import fonts_dir as _uploaded
    for c in (_uploaded(),                                    # what you added
              os.path.join(os.path.dirname(here), "fonts"),   # repo root/fonts
              os.path.join(here, "fonts"),                    # package/fonts
              os.path.join(os.getcwd(), "fonts"),             # launch dir
              os.path.join(os.path.dirname(here), "assets", "fonts"),
              os.path.join(os.getcwd(), "assets", "fonts")):
        c = os.path.abspath(c)
        if c not in out:
            out.append(c)
    return tuple(out)


def default_font_path() -> str:
    """The face to typeset in when the project names none of its own."""
    env = os.environ.get("MANGATL_FONT", "")
    if env and os.path.exists(env):
        # Absolute, even when the setting is relative. `.env` in the repository
        # says `MANGATL_FONT=fonts/CCWildWords.ttf`, which resolves fine and is
        # then a DIFFERENT STRING from the same file's entry in the font list -
        # so the menu could not find the face it was showing and fell back to
        # printing the filename, extension and all. Everything else in the app
        # hands round absolute paths; this was the one that did not.
        return os.path.abspath(env)
    # a typesetting font by preference...
    #
    # This list used to start with `CCWildWords.ttf` and `AnimeAce.ttf`, which
    # are the two faces this job actually wants and the two that may not be
    # shipped: Comicraft's desktop licence forbids app integration outright,
    # and Blambot's free licence forbids redistribution, with a paid tier that
    # explicitly does not cover Pro faces at all. Both files are gone from
    # `fonts/`; see `fonts/LICENSES.md`.
    #
    # They are still named here, and first, on purpose. `_font_dirs()` looks in
    # the user's OWN uploaded-fonts folder before the bundled one, so anybody
    # who has licensed either face gets it back simply by adding it - which is
    # the arrangement that costs nothing and takes nothing away.
    for d in _font_dirs():
        for name in ("CCWildWords.ttf", "AnimeAce.ttf", "ComicNeue-Bold.ttf"):
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    # ...then whatever else is bundled...
    for d in _font_dirs():
        try:
            for f in sorted(os.listdir(d)):
                if f.lower().endswith((".ttf", ".otf")):
                    return os.path.join(d, f)
        except OSError:
            pass
    # ...then anything the machine itself ships.
    for p in ("/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "C:\\Windows\\Fonts\\arial.ttf",
              "C:\\Windows\\Fonts\\segoeui.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if os.path.exists(p):
            return p
    raise FileNotFoundError("No usable font. Set MANGATL_FONT to a .ttf path.")


def spare_font() -> str:
    """The default face, or nothing at all.

    Asking for a fallback must never be what takes a page down: the project
    already names a font, and a missing spare is only the loss of a safety net.
    """
    try:
        return default_font_path()
    except FileNotFoundError:
        return ""


PAD_PX = 4          # breathing room inside a text box


# A POINT IS NOT A SIZE, AND THIS IS THE NUMBER THAT MAKES IT ONE.
#
# lee: *"can you make rhe tyesetting addap to teh fonsts some font have smaller
# text and some have bigger text and teh typesetter shoud make both visulay the
# sam size not teh sma efont number"*.
#
# He is right, and the spread across this app's own eleven faces is not
# marginal. Cap height as a fraction of the point size - which is what the eye
# measures a line of capitals by:
#
#     Anton      0.86      Comic Neue Bold  0.69      Gochi Hand   0.58
#     Bangers    0.75      Patrick Hand     0.66      Nanum Pen    0.56
#     Chewy      0.75      Gaegu            0.61
#     Jua        0.74
#
# So "30pt" in Nanum Pen Script draws capitals a third shorter than "30pt" in
# Anton. Every number in this app - the size box, the minimum and the maximum,
# the 1.15 a shout is scaled by, the size the fitter settles on - meant a
# different thing for every face, and the place it shows is two boxes set to
# the same number that plainly do not match.
#
# The reference is Comic Neue Bold's, the speech face: a size goes on meaning
# what it has always meant on the face most pages are set in, so existing
# chapters move least and the blocks that move are the ones that were wrong.
CAP_REF = 0.69


@lru_cache(maxsize=512)
def cap_ratio(path: str) -> float:
    """How tall this face's capitals are, as a fraction of its point size.

    `CAP_REF` when the file cannot be read or answers something absurd, and
    that means "do not scale this one" - the safe direction, because a face
    nobody could measure is left rendering exactly as it does today.
    """
    try:
        f = ImageFont.truetype(path, 100)
        box = f.getbbox("H")
        r = (box[3] - box[1]) / 100.0
    except Exception:
        return CAP_REF
    return r if 0.30 <= r <= 1.20 else CAP_REF


def px_for(path: str, size) -> int:
    """The number to ASK PIL for, so that `size` means a visual size.

    One multiplication, in the one place every face in this app is loaded. The
    fitter, the renderer, the width cache, the mark stamper and the sample
    images all go through `_font`, so they all speak the same unit without
    having to know about it - and `lay.font_size` goes on meaning the number
    the panel shows.
    """
    try:
        size = float(size)
    except (TypeError, ValueError):
        return 1
    # `float("nan")` and `float("inf")` both survive the line above and both
    # raise on the way into `int()` - a size box is a text field and a saved
    # chapter is a JSON file, so neither is hypothetical.
    if not math.isfinite(size):
        return 1
    return max(1, min(4000, int(round(size * CAP_REF / cap_ratio(path)))))


@lru_cache(maxsize=256)
def _font(path: str, size: int):
    """Load a face, falling back to the default rather than failing.

    CACHED ON THE NOMINAL SIZE, which is the size everything else in this app
    talks in - `px_for` turns it into the number PIL is asked for, and two
    faces asked for the same visual size are two different cache entries
    because their paths differ.

    A font the user picked may have moved or be unreadable. Losing the whole
    page render over that is not acceptable - typeset it in the default face and
    let the flag surface the problem."""
    try:
        return ImageFont.truetype(path, px_for(path, size))
    except (OSError, ValueError):
        fallback = spare_font()
        if fallback and fallback != path:
            return ImageFont.truetype(fallback, px_for(fallback, size))
        raise


@lru_cache(maxsize=100_000)
def _text_w(path: str, size: int, s: str) -> float:
    f = _font(path, size)
    w = f.getlength(s)
    if "—" in s:
        bar = em_dash_glyph(path, size)
        if bar:                       # synthesized dash: reserve its real width
            w += (bar[0] - f.getlength("—")) * s.count("—")
    # ...and the same for a mark the face cannot draw. The fitter measures
    # every candidate line through here, so a stamped mark that is not counted
    # is a line the fitter thinks is narrower than it is - and the first thing
    # anybody sees is a heart sitting on the balloon edge.
    for ch, got in marks_in(s, path, size).items():
        w += (got[0] - f.getlength(ch)) * s.count(ch)
    return w


_DESCENDS = set("gjpqy,;()[]{}/\\@$_QJ")


@lru_cache(maxsize=1024)
def ink_extents(path: str, size: int, descenders: bool) -> tuple[float, float]:
    """Where a line's INK sits, relative to the anchor the renderer draws at.

    Returns (top, bottom) offsets from an "mm"-anchored origin. Two things
    depend on this:

    * A line box is `size * leading` tall, but the letters only fill part of
      it. Measuring the bubble's chord across the whole box makes every line
      narrower than it needs to be - worst at the top and bottom of an oval,
      where the box corners hang out over the curve but no ink ever reaches
      them. Measuring across the ink band instead is what lets the fitter use
      a bubble's real width.

    * "mm" centres on the font's ascender/descender box. All-caps typesetting
      never uses the descender, so the line comes out sitting low (or high -
      it depends on the face). Centring on the ink instead puts the text
      where the eye expects it.

    A stroke allowance is included, since the renderer outlines the letters.
    """
    f = _font(path, size)
    probe = "AHMOWX" + ("gjpqy," if descenders else "")
    try:
        _, y0, _, y1 = f.getbbox(probe, anchor="mm")
    except Exception:
        asc, desc = f.getmetrics()
        y0, y1 = -(asc + desc) / 2, (asc + desc) / 2
    pad = size / 14.0 + 1.0            # the outline the renderer adds
    return (float(y0) - pad, float(y1) + pad)


def _has_descenders(text: str) -> bool:
    return any(c in _DESCENDS for c in text)


# -------------------------------------------------------------- the em-dash
# Comic typesetting faces routinely ship a hyphen and no em-dash. The old
# stand-in was a filled rectangle, and it showed: dead straight, square
# cornered, obviously a machine part sitting in a row of wobbling hand-drawn
# letters. So borrow the shape instead. Take the em-dash outline out of a
# Comic Sans-alike - real Comic Sans when the machine has it, the bundled
# Comic Neue otherwise - and rescale it to the host font's own stroke weight
# and to a proper em of length. The ends keep the donor's rounding.

_EM_DONORS = (
    "C:/Windows/Fonts/comic.ttf",
    "C:/Windows/Fonts/comicbd.ttf",
    "C:/WINDOWS/Fonts/comic.ttf",
    "/Library/Fonts/Comic Sans MS.ttf",
    "/System/Library/Fonts/Supplemental/Comic Sans MS.ttf",
    "fonts/ComicNeue-Bold.ttf",
    "fonts/ComicNeue-Regular.ttf",
    "assets/fonts/ComicNeue-Bold.ttf",
)

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))


@lru_cache(maxsize=1)
def em_dash_donor() -> str:
    """The face to lift an em-dash outline from. '' when there is none."""
    seen, cands = set(), [os.environ.get("MANGATL_EM_DASH_FONT", "")]
    for rel in _EM_DONORS:
        cands.append(rel)
        if not os.path.isabs(rel) and ":" not in rel:
            # the editor's working directory is not guaranteed to be the
            # project root, so also look beside the package itself
            cands.append(os.path.join(os.path.dirname(_PKG_DIR), rel))
            cands.append(os.path.join(_PKG_DIR, rel))
    for p in cands:
        if not p or p in seen:
            continue
        seen.add(p)
        try:
            if os.path.exists(p) and font_supports(p, "—") and usable_font(p):
                return p
        except Exception:
            continue
    return ""


@lru_cache(maxsize=512)
def _glyph_ink(path: str, size: int, ch: str):
    """One character's ink, cropped tight.

    Returns (mask, top, stroke) - an 8-bit PIL image of just the ink, the y of
    its first row relative to an "mm"/"lm" anchor, and the median thickness of
    its inked columns. Thickness is a median rather than the bounding height
    because a hand-drawn hyphen is a tilted wedge: its box is far taller than
    the stroke actually is, and matching the box would give a dash twice the
    weight of the letters around it.
    """
    from PIL import Image, ImageDraw
    try:
        f = _font(path, size)
    except Exception:
        return None
    # In DRAWN pixels, not in the size that was asked for. A face whose
    # capitals are small for its em is opened larger than the number says
    # (`px_for`), and a sheet padded from the number would crop it.
    px = px_for(path, size)
    pad = max(16, px * 2)
    img = Image.new("L", (pad * 4, pad * 3), 0)
    ImageDraw.Draw(img).text((pad, pad + px), ch, font=f, anchor="lm",
                             fill=255)
    a = np.asarray(img) > 96
    ys, xs = np.nonzero(a.any(axis=1))[0], np.nonzero(a.any(axis=0))[0]
    if not ys.size or not xs.size:
        return None
    cols = a[:, xs].sum(axis=0)
    stroke = float(np.median(cols[cols > 0])) if (cols > 0).any() else 1.0
    box = (int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1)
    return (img.crop(box), float(ys[0] - (pad + px)), stroke)


@lru_cache(maxsize=256)
def em_dash_glyph(path: str, size: int):
    """An em-dash for a font that has no glyph for one.

    Returns (advance, top, mask): the width to reserve in the layout, the y of
    the mask's first row relative to the anchor the renderer draws at, and an
    8-bit alpha mask of the dash. None when the font can draw its own.

    The mask is the donor's em-dash rendered at whatever size makes its stroke
    match the host font's hyphen, then stretched horizontally to a real em. It
    is centred on the host's own hyphen band so it sits at the height the rest
    of the typesetting expects. If no donor is available at all it degrades to a
    plain bar, which is what this used to be unconditionally.
    """
    if not path or size < 4 or font_supports(path, "—"):
        return None
    from PIL import Image

    # EVERY NUMBER BELOW IS IN DRAWN PIXELS.
    #
    # The em fractions here - three quarters of an em long, a fifth of an em
    # thick at most, side bearings of a seventh - describe the dash next to the
    # LETTERS, and the letters are drawn at `px_for(path, size)` rather than at
    # the size asked for. Measured against the size instead, a face opened
    # larger than its number (Gaegu, whose capitals are 0.62 of its em) got a
    # hyphen a fifth wider than the em-dash meant to be half again longer.
    px = px_for(path, size)
    hy = _glyph_ink(path, size, "-")
    if hy:
        hmask, htop, hstroke = hy
        hw, hmid = hmask.width, htop + hmask.height / 2.0
    else:                       # no hyphen either: invent a plausible stroke
        hw, hstroke, hmid = px * 0.42, px * 0.08, 0.0
    thick = max(1, min(int(round(hstroke)), int(round(px * 0.20))))
    # A real em-dash runs about three quarters of an em, and in every comic
    # face measured it is comfortably past 1.5x the hyphen. Take the longer.
    width = max(thick * 3, int(round(max(px * 0.72, hw * 1.55))))

    mask = None
    donor = em_dash_donor()
    if donor:
        probe = _glyph_ink(donor, 64, "—")
        if probe and probe[2] > 0:
            # render the donor at the size whose stroke already matches ours,
            # so the only rescaling left is a harmless horizontal stretch
            dsize = max(6, min(900, int(round(64 * thick / probe[2]))))
            got = _glyph_ink(donor, dsize, "—")
            if got and got[0].height <= max(2, thick * 3):
                mask = got[0]
    if mask is None:
        mask = Image.new("L", (max(2, width), thick), 255)
    if mask.width != width:
        mask = mask.resize((width, mask.height), Image.LANCZOS)
    top = hmid - mask.height / 2.0
    advance = width + max(2.0, px * 0.14)       # side bearings
    return (float(advance), int(round(top)), mask)


# ------------------------------------------------------- marks in a line ----
#
# lee, with a crop of 「これから本番♥」: *"i want teh read text to be able to read
# stuff like haearts and other thiungs that text can usualy have ... i wan a
# big librey of icons that can be put there"*.
#
# A mark IN A LINE, and nothing else - lee: *"the app shou only worry about
# symobys in the text not any other symobs"*. A sound painted on the artwork is
# a sound effect and has its own box; a mark typeset among the words is part of
# what the balloon says.
#
# The em-dash below is the same idea and came first: a comic face that ships
# only a hyphen still gets a real long dash, drawn by hand and stamped. This
# generalises it, and the reason it has to exist at all is measured - of the
# sixteen faces this app ships, ComicNeue (the speech face) has NOT ONE of the
# eighteen marks manga uses. `♥` in a line of Comic Neue is an empty box.
#
# TWO SOURCES, IN ORDER. lee chose both: *"A with B behind it as a fallback"*.
#
#   1. `marks.py` - the shape drawn here. Round, short-pointed, the heart manga
#      draws. Every mark that matters has one.
#   2. A font on this machine that HAS the character. Nothing new is shipped
#      for this: `_font_dirs()` and the system folders already hold faces with
#      wide symbol coverage, and asking them costs a lookup rather than a
#      licence. It catches a mark nobody has drawn yet.
#
# ...and if neither can, the character is left exactly as it is and the font
# draws whatever it draws. Dropping it would lose what the balloon says without
# saying so, which is worse than a mark that looks wrong.
MARK_CAP = 0.86       # of the host's cap height, so it sits with the capitals
# Side bearing either side, as a fraction of the size. 0.10 was the first
# guess and `♪♪` came out with a fifth of an em between the two notes, which
# reads as a gap rather than a pair - two marks in a row is the case that shows
# a bearing up, because theirs add.
MARK_BEARING = 0.055

# EVERY character this is willing to substitute, and no others.
#
# lee: *"the app shou only worry about symobys in the text not any other
# symobs"*. So this is a LIST and not a rule like "anything outside Latin-1":
# a rule would sweep up source-language punctuation, the long-vowel mark, and
# every kanji on a page the reader failed to translate, and start stamping
# pictures over them.
#
# The drawn set, plus the few the donor supplies. Nothing here is a shape
# somebody draws ON the artwork - a sound effect is a box of its own.
#
# `marks.PICKER` is the one list, because it is also what the picker shows: a
# character somebody can insert and the app then refuses to draw would be a
# button that does nothing.
MARK_CHARS = frozenset(_marks.CHARS) | frozenset(_marks.GLYPHS)
_MARK_CHARS = MARK_CHARS        # the old private name, still used below


@lru_cache(maxsize=64)
def mark_donor(ch: str) -> str:
    """A face on this machine that can draw `ch`. '' when there is none.

    Searched over the app's own font folders and the usual system ones. This
    is the B half of lee's answer and it ships nothing: a machine with any
    general-purpose font on it has most of these characters already.
    """
    seen = []
    for d in list(_font_dirs()) + [
            "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype",
            "/usr/share/fonts", "C:/Windows/Fonts",
            "/System/Library/Fonts/Supplemental", "/Library/Fonts"]:
        try:
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d)):
                if name.lower().endswith((".ttf", ".otf")):
                    seen.append(os.path.join(d, name))
        except OSError:
            continue
    for p in seen:
        try:
            if font_supports(p, ch) and usable_font(p):
                return p
        except Exception:
            continue
    return ""


@lru_cache(maxsize=4096)
def mark_glyph(path: str, size: int, ch: str):
    """(advance, top, mask) for a mark the host face cannot draw itself.

    None when the font has its own glyph - which is the case that matters most
    for the faces that DO carry one. Jua has a heart and Patrick Hand has a
    heart, and a drawn substitute in either would be a stranger dropped into a
    line that already had the letter.

    `top` is the y of the mask's first row relative to the "lm"/"mm" anchor the
    renderer draws at, the same convention `em_dash_glyph` uses, so the two go
    down the same path in `render.draw_line`.
    """
    if not path or size < 4 or not ch:
        return None
    # ON THE LIST OR NOT AT ALL, and the guard belongs HERE rather than only in
    # `marks_in`, which is what used to hold it. This is the function that
    # decides whether to substitute, and without the check it would draw ANY
    # character a font on this machine happens to have - so a page whose read
    # failed, with Japanese still sitting in `dst_text`, would get every
    # hiragana stamped out of the system gothic face at cap height.
    #
    # lee: *"the app shou only worry about symobys in the text not any other
    # symobs"*. A test asks it of あ, 漢, ー and ！.
    if ch not in MARK_CHARS:
        return None
    try:
        if font_supports(path, ch):
            return None
    except Exception:
        return None
    # Where the capitals sit, so the mark sits with them rather than on the
    # baseline or in the middle of the em.
    # In DRAWN pixels throughout: the mark sits beside the letters, and the
    # letters are drawn at `px_for(path, size)`. The measured branch already
    # is - `_glyph_ink` opens the face the same way the renderer does - and the
    # fallback has to be, or a face opened larger than its number gets a mark
    # sized for the number.
    px = px_for(path, size)
    cap = _glyph_ink(path, size, "H")
    if cap:
        ctop, chh = float(cap[1]), float(cap[0].height)
    else:
        chh = px * CAP_REF
        ctop = -chh
    h = max(2, int(round(chh * MARK_CAP)))

    # FROM A REAL FACE FIRST. lee, over the hand-drawn set: *"instad of
    # making your own glyphs find some charter only and use those"*. The three
    # faces in fonts/marks/ are tiny OFL subsets (Noto Emoji, Noto Sans
    # Symbols 2, Noto Music - renamed, as the licence requires of a modified
    # copy) that between them carry every character the picker offers, so the
    # picture is a type designer's and the same on every machine. The drawn
    # shapes in `marks.py` stay behind them for a build these files have been
    # stripped from, and the system-font donor behind that.
    mask = None
    for face in _mark_faces():
        if font_supports(face, ch):
            mask = _font_mask(face, ch, h)
            if mask is not None:
                break
    if mask is None:
        got = _marks.for_char(ch)
        if got:
            try:
                mask = _marks.mask(got[0], h, hollow=got[1] * h)
            except Exception:
                mask = None
    if mask is None:
        mask = _donor_mask(ch, h)
    if mask is None:
        return None                 # let the font draw whatever it draws
    top = ctop + (chh - mask.height) / 2.0
    return (float(mask.width + px * MARK_BEARING * 2.0),
            int(round(top)), mask)


@lru_cache(maxsize=1)
def _mark_faces() -> tuple:
    """The bundled mark faces that exist on this install, in preference
    order. Emoji first: where two carry one character (♥, ⚡, ☠) the emoji
    forms sit better among the others from the same face."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "fonts", "marks")
    out = []
    for name in ("marks-emoji.ttf", "marks-symbols.ttf", "marks-music.ttf"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            out.append(p)
    return tuple(out)


def _donor_mask(ch: str, h: int):
    """`ch` rendered from a system font that has it - the last net."""
    donor = mark_donor(ch)
    if not donor:
        return None
    return _font_mask(donor, ch, h)


def _font_mask(path: str, ch: str, h: int):
    """`ch` rendered from `path`, cropped to its ink, `h` tall."""
    from PIL import Image, ImageDraw
    for px in (h * 2, int(h * 1.4), h, max(4, h // 2)):
        try:
            f = _font(path, max(4, int(px)))
            l, t, r, b = f.getbbox(ch)
        except Exception:
            continue
        if r <= l or b <= t:
            continue
        im = Image.new("L", (r - l, b - t), 0)
        ImageDraw.Draw(im).text((-l, -t), ch, font=f, fill=255)
        if im.height != h:
            w = max(1, int(round(im.width * h / float(im.height))))
            im = im.resize((w, h), Image.LANCZOS)
        return im
    return None


def marks_in(line: str, path: str, size: int) -> dict:
    """{character: (advance, top, mask)} for every mark in `line` this face
    cannot draw. Empty when there are none, which is nearly every line."""
    out = {}
    for ch in set(line):
        if ch in _MARK_CHARS:
            got = mark_glyph(path, size, ch)
            if got:
                out[ch] = got
    return out


def gutters(size: int, bubble_h: float, cfg: "TypesetConfig") -> tuple[float, float]:
    """(vertical, edge) clearance to leave inside the bubble outline.

    Both are the largest of the claims in the config, so a small bubble still
    gets real air and a large one is not padded out of proportion. The edge
    figure also carries the outline the renderer paints around each glyph,
    which the width measurements know nothing about - without it a line that
    "fits" can still have its stroke sitting on the bubble edge.
    """
    em = size * cfg.pad_em
    e = max(float(cfg.pad_px), em) + size / 14.0 + 1.0
    v = max(float(cfg.v_margin_px), e, bubble_h * cfg.v_margin_frac)
    return v, e


# ---------------------------------------------------------------- chord widths

def _row_chords(mask: np.ndarray):
    """(has_ink, first_x, last_x) of the LONGEST UNBROKEN RUN in every row.

    Not the span from the first set pixel to the last. That was the same
    answer for every mask this was written against - a balloon interior is one
    piece, so each of its rows is one run - and a wrong answer for the masks it
    was not written against: a region whose mask has a HOLE in it reported the
    hole as room.

    lee's page 008 is the case. The words sit on the flat back of a panel with
    a character in it, so the segmenter's mask is that flat area with her hair
    punched out of the middle. Every row of it runs from x=89 to x=295 with a
    bite taken out around x=183..250, and first-to-last called that a 206px
    chord. The fitter set three lines across it at 19pt, and then
    `render_page` - which composites each region through this very mask -
    deleted every letter standing over the hair. "...I MEAN, / THIS IS ONLY /
    NATURAL!" came out with a fifth of its ink gone, ONLY hollowed straight
    through the middle.

    A line of type is one unbroken thing, so the room it has is one unbroken
    run, and the widest one is the one to offer it. On a mask with no holes
    that is the old answer to the pixel; on a mask with a hole it is the only
    answer that does not promise room the renderer will take back.

    Vectorised over the whole mask at once: pad each row with a dead column at
    either end and difference along the row, so every rise is a run's start and
    every fall its end. All the runs of all the rows come out as two flat
    arrays, and the longest per row is a lexsort plus one pass for the last of
    each group.

    The work is done over the mask's bounding box, not the mask. These masks
    are page-sized whatever the balloon is - a 90x200 bubble arrives inside a
    960x1365 field of zeros - so cropping first is what keeps this cheap.
    """
    m = mask.astype(bool)
    h = m.shape[0]
    rows = m.any(axis=1)
    first = np.zeros(h, dtype=np.int64)
    last = np.full(h, -1, dtype=np.int64)
    ys = np.flatnonzero(rows)
    if not ys.size:
        return rows, first, last
    y0, y1 = int(ys[0]), int(ys[-1])
    band = m[y0:y1 + 1]
    xs = np.flatnonzero(band.any(axis=0))
    x0, x1 = int(xs[0]), int(xs[-1])
    sub = np.ascontiguousarray(band[:, x0:x1 + 1])
    # WHAT WAS TRIED AND DROPPED: forgiving the specks. These masks are cut and
    # closed by us, so they carry pin-prick holes - the share for lee's page 014
    # has seven, six of them a single pixel - and one pixel is enough to split a
    # row, more so once the gutter erosion has widened it. Two answers were
    # measured over his 23 pages: bridging gaps of two pixels or fewer here, and
    # filling enclosed holes under 24px before the distance transform. The first
    # changed not one block of 163 and cost 13px more deleted ink; the second
    # changed three - one better, one worse, one only broken differently - and
    # cost 4px. Neither paid for itself, and a rule you cannot tell from its own
    # absence is not a rule.
    pad = np.zeros((sub.shape[0], sub.shape[1] + 2), np.int8)
    pad[:, 1:-1] = sub
    d = np.diff(pad, axis=1)
    sr, sc = np.nonzero(d == 1)          # run starts, in `sub` columns
    _er, ec = np.nonzero(d == -1)        # run ends, exclusive
    if sr.size:
        # Within a row the runs come out left to right and pair up in order, so
        # `sc` and `ec` line up entry for entry. Sorting by (row, length) puts
        # each row's longest run last in its group, and the group ends are the
        # entries where the row number is about to change.
        order = np.lexsort((ec - sc, sr))
        rs, cs, ce = sr[order], sc[order], ec[order]
        keep = np.flatnonzero(np.append(np.diff(rs) != 0, True))
        yy = rs[keep] + y0
        first[yy] = cs[keep] + x0
        last[yy] = ce[keep] - 1 + x0
    return rows, first, last


def chord_profile(mask: np.ndarray) -> tuple[np.ndarray, int, int]:
    """For each row of the mask, the width of its horizontal span.

    Returns (widths, y_top, y_bottom). Uses the span between the first and last
    set pixel, so a bubble with a tail reports the tail rows as narrow, which is
    exactly what we want - text should not run into the tail.
    """
    rows, first, last = _row_chords(mask)
    ys = np.flatnonzero(rows)
    if ys.size == 0:
        return np.zeros(0), 0, 0
    widths = np.where(rows, last - first + 1, 0).astype(np.float32)
    return widths, int(ys[0]), int(ys[-1])


def band_width(widths: np.ndarray, ya: int, yb: int) -> float:
    """Narrowest chord across rows [ya, yb) - the safe width for a line."""
    ya = max(0, ya)
    yb = min(len(widths), max(ya + 1, yb))
    seg = widths[ya:yb]
    return float(seg.min()) if seg.size else 0.0


def chord_edges(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """First and last set pixel of every row - the two ends of its chord.

    `chord_profile` measures how WIDE each row is, which is all you need to
    ask whether a line fits. It is not enough to ask whether a whole block
    fits on one axis, because that question is about where the room is, not
    how much of it there is. Rows with no pixels report an empty chord
    (left > right), which every consumer here reads as "no room".
    """
    _rows, first, last = _row_chords(mask)
    return first.astype(np.float32), last.astype(np.float32)


def band_span(left: np.ndarray, right: np.ndarray,
              ya: int, yb: int) -> tuple[float, float]:
    """The columns every row of band [ya, yb) has - its common chord.

    Narrower than the narrowest row when the rows are staggered, which is the
    honest answer: a line of type spans the whole band, so a column only one
    of its rows can reach is a column it cannot use.
    """
    ya = max(0, ya)
    yb = min(len(left), max(ya + 1, yb))
    if yb <= ya:
        return 0.0, -1.0
    return float(left[ya:yb].max()), float(right[ya:yb].min())


class _RowRanges:
    """The same three band questions as above, answered in constant time.

    `band_width` and `band_span` are three tiny reductions over a slice of a
    row profile, and the fit search asks them about a million times a page -
    once per line, per line count, per placement, per leading, per size. Each
    one is a few microseconds of numpy call overhead over a dozen-odd floats,
    and that overhead was a third of the whole typesetting time.

    A sparse table pays for the reduction once. Level `j` holds the answer for
    every window of exactly 2^j rows, built by folding the level below onto
    itself, so any range is covered by two overlapping power-of-two windows and
    answered by combining them. Overlap is harmless because min and max are
    idempotent - counting a row twice does not change the smallest or largest.
    Building costs a handful of full-array ops per bubble; every question after
    that is two lookups, and a whole block's worth of bands is asked at once.

    The answers are the same numbers the scalar pair returns, clamped the same
    way, including the empty-band answer of (0, -1) that every caller reads as
    "no room here".
    """

    def __init__(self, widths, left, right):
        n = int(len(widths))
        self.n = n
        if n == 0:
            return
        self._log = np.zeros(n + 1, dtype=np.int64)
        if n >= 2:
            self._log[2:] = np.log2(np.arange(2, n + 1)).astype(np.int64)
        lv = int(self._log[n]) + 1

        def build(a, fold, fill):
            t = np.full((lv, n), fill, dtype=np.float32)
            t[0] = a
            for j in range(1, lv):
                half = 1 << (j - 1)
                m = n - (1 << j) + 1
                if m <= 0:
                    break
                t[j, :m] = fold(t[j - 1, :m], t[j - 1, half:half + m])
            return t

        self._wmin = build(widths, np.minimum, np.inf)
        self._lmax = build(left, np.maximum, -np.inf)
        self._rmin = build(right, np.minimum, np.inf)

    def bands(self, ya: np.ndarray, yb: np.ndarray):
        """(narrowest width, common left, common right) for every band."""
        n = self.n
        ya = np.maximum(ya, 0)
        yb = np.minimum(n, np.maximum(ya + 1, yb))
        if n == 0:
            z = np.zeros(len(ya), dtype=np.float32)
            return z, z, z - 1.0
        bad = yb <= ya
        qa = np.where(bad, 0, ya)
        qb = np.where(bad, 1, yb)
        k = self._log[qb - qa]
        off = qb - (1 << k)
        w = np.minimum(self._wmin[k, qa], self._wmin[k, off])
        lo = np.maximum(self._lmax[k, qa], self._lmax[k, off])
        hi = np.minimum(self._rmin[k, qa], self._rmin[k, off])
        if bad.any():
            w = np.where(bad, 0.0, w)
            lo = np.where(bad, 0.0, lo)
            hi = np.where(bad, -1.0, hi)
        return w, lo, hi


def line_axis(spans: list, used: list) -> float:
    """The one vertical line a whole block of text is centred on.

    Every line of a block shares a centre - that is what a block IS, on the
    page and in every typesetting guide there is. Centring each line on its
    own chord instead makes them wander in anything that is not left-right
    symmetric, and lee's narration blocks came down the page as a staircase,
    one step per line, because the shape they were measured in was the ragged
    outline of the Japanese they replace and no two of its chords agree.

    The axis is chosen from the lines as they actually came out, not from the
    room they were offered. A line `w` wide sitting in a band that runs from
    `a` to `b` can be centred anywhere in [a + w/2, b - w/2] without touching
    either edge, so the block's axis is any point inside every one of those
    intervals, and the one to pick is the one nearest the middle of the shape
    at that height. Asking the question this way round costs nothing: a block
    that fits its bands still fits them. Asking it the other way round - the
    strip every line could reach WHATEVER it turned out to say - throws size
    away, and cost lee's two-lobed bud two points on words that fitted it.

    When the intervals do not all overlap, the shape is too lopsided to hold
    this block dead straight; the midpoint of the crossed pair is the least
    bad answer there is, splitting the overhang evenly rather than letting
    one line hang off one side.
    """
    if not spans:
        return 0.0
    used = list(used) + [0.0] * (len(spans) - len(used))
    lo = max(a + w / 2 for (a, _), w in zip(spans, used))
    hi = min(b - w / 2 for (_, b), w in zip(spans, used))
    if hi < lo:
        return (lo + hi) / 2
    want = sum(a + b for a, b in spans) / (2 * len(spans))
    return min(hi, max(lo, want))


class BubbleGeom:
    """A bubble's geometry, measured once and reused across the fit search.

    The usable width for a line is NOT its chord minus a horizontal margin.
    On a curved edge the eye judges the PERPENDICULAR distance to the outline,
    and a line of type is a band several rows tall: its corners reach the arc
    long before its middle does. Insetting horizontally leaves those corners
    hard against the curve, which is exactly the "too close to the edge" a
    reader sees in a round bubble even when the arithmetic says it fits.

    So the safe area is the bubble ERODED by the gutter - every point at least
    that far from the outline in any direction - and chords are taken across
    that instead. On a rectangle it comes to the same thing; on a circle it
    pulls the top and bottom lines in, which is the whole point.
    """

    def __init__(self, mask: np.ndarray):
        m = np.ascontiguousarray((mask > 0).astype(np.uint8))
        self.mask = m
        # distance from each interior pixel to the nearest pixel outside
        self.dist = cv2.distanceTransform(m, cv2.DIST_L2, 5)
        self._edges: dict = {}
        self._ranges: dict = {}
        ys = np.flatnonzero(m.any(axis=1))
        self.y0, self.y1 = (int(ys[0]), int(ys[-1])) if ys.size else (0, -1)
        self.height = self.y1 - self.y0 + 1 if ys.size else 0
        self._cache: dict = {}

    def _measure(self, key: float):
        """Everything about the bubble at one inset, measured in one pass.

        The widths and the two chord ends are the SAME two `argmax` passes over
        the same eroded mask, and asking for them separately measured every
        bubble twice. They are cached together and handed out by the three
        accessors below.
        """
        got = self._cache.get(key)
        if got is None:
            inner = (self.dist >= key).astype(np.uint8)
            rows, first, last = _row_chords(inner)
            ys = np.flatnonzero(rows)
            if ys.size:
                y0, y1 = int(ys[0]), int(ys[-1])
                widths = np.where(rows, last - first + 1, 0).astype(np.float32)
            else:
                y0 = y1 = 0
                widths = np.zeros(0)
            left = first.astype(np.float32)
            right = last.astype(np.float32)
            got = self._cache[key] = (inner, widths, y0, y1, left, right)
        return got

    def inset(self, pad: float):
        """(mask, widths, y_top, y_bottom) for the bubble shrunk by `pad`."""
        inner, widths, y0, y1, _l, _r = self._measure(round(float(pad), 2))
        return inner, widths, y0, y1

    def edges(self, pad: float):
        """(left, right) chord ends for the bubble shrunk by `pad`."""
        got = self._measure(round(float(pad), 2))
        return got[4], got[5]

    def ranges(self, pad: float) -> "_RowRanges":
        """Constant-time band queries for the bubble shrunk by `pad`."""
        key = round(float(pad), 2)
        got = self._ranges.get(key)
        if got is None:
            _m, widths, _y0, _y1, left, right = self._measure(key)
            got = self._ranges[key] = _RowRanges(widths, left, right)
        return got


# ------------------------------------------------------------- line breaking

def _break_penalty(prev_word: str, next_word: str) -> float:
    p = 0.0
    if prev_word and prev_word[-1] in _GOOD_BREAK_AFTER:
        p -= 0.35
    if next_word and next_word.lower().strip(".,!?") in _BAD_BREAK_BEFORE:
        p += 0.25
    return p


# NO hyphenation, ever - lee tried it and hated it. The fitter uses line
# breaks and size alone; a word is never split. A word wider than the box at
# the absolute floor falls through to the clamped-and-flagged path instead.
#
# Breaking at a dash the AUTHOR wrote is a different thing and it is allowed,
# once nothing else has worked. Hyphenation invents a hyphen and puts it where
# a dictionary says a word may be cut; this only ever breaks where the text
# already has a dash or a row of dots, and adds nothing. Every typesetter does
# it: GLOW-SAN! becomes GLOW- / SAN!, LOOK CLOSELY... becomes LOOK / CLOSELY /
# ..., and the balloon keeps its point size instead of dropping under the
# minimum. lee, with eight before-and-afters: *"when there isnt enoghth space
# to have teh minimuin text size, the tyoseeter can create new line where ther
# are already dahses or ...."*.
_DASHES = "-‐‑‒–—―"
_DOTS = ".…"


def author_breaks(word: str) -> list[str]:
    """`word` cut at the dashes and dot runs already in it.

    A dash keeps the piece before it - GLOW-SAN! is GLOW- then SAN!, the way
    it is set on the page, because a line ending in a bare GLOW reads as a
    different word. A row of dots keeps the piece after it - CLOSELY... is
    CLOSELY then ..., because the dots are the pause and the pause belongs
    with what comes next.

    A cut needs material on both sides, so a trailing dash or a leading
    ellipsis leaves the word whole. A single full stop is a full stop and
    never a break; two or more, or the one-character ellipsis, is a pause.

    Nothing empty is ever appended, so there is no filter on the way out. A
    `[p for p in parts if p]` here would have swallowed the leading-ellipsis
    guard below - with the filter in place, dropping the guard changed
    nothing, and a rule that cannot be told from its own absence is not a
    rule anybody can rely on.
    """
    parts, cur, i, n = [], "", 0, len(word)
    while i < n:
        ch = word[i]
        if ch in _DASHES:
            while i < n and word[i] in _DASHES:
                cur += word[i]
                i += 1
            # Material on both sides or it is not a break: a trailing dash is
            # just how the line ends, and a leading one (-WELL, an interrupted
            # speaker) would otherwise be left standing alone on a line of its
            # own, which is the one thing a dash must never do.
            if i < n and cur.strip(_DASHES):
                parts.append(cur)
                cur = ""
            continue
        if ch in _DOTS:
            run = ""
            while i < n and word[i] in _DOTS:
                run += word[i]
                i += 1
            if cur and (len(run) > 1 or "…" in run):
                parts.append(cur)
                cur = ""
            cur += run
            continue
        cur += ch
        i += 1
    if cur:
        parts.append(cur)
    return parts


def author_break_tokens(text: str) -> "tuple[list[str], list[bool]]":
    """`text` as tokens the fitter may break between, and which of those
    tokens rejoin with NO space when they land on the same line."""
    toks: list[str] = []
    glue: list[bool] = []
    for w in text.split():
        for k, p in enumerate(author_breaks(w)):
            toks.append(p)
            glue.append(k > 0)
    return toks, glue


def rejoin_author_breaks(lines: list, toks: list, glue: list) -> list:
    """The fitter's lines with every pair it did NOT break put back together.

    The fitter is handed the pieces spaced apart so it may break between them;
    two pieces that end up on one line are one word again, and must be drawn
    as one - GLOW- SAN! with a space in it is not a word anybody wrote.
    """
    out, at = [], 0
    for ln in lines:
        n = len(ln.split())
        built = ""
        for k in range(at, at + n):
            if k >= len(toks):
                return list(lines)          # not the sequence we handed out
            built += (toks[k] if (k == at or glue[k]) else " " + toks[k])
        at += n
        out.append(built)
    if at != len(toks):
        return list(lines)
    return out


def wrap_to_width(text: str, measure: Callable[[str], float],
                  space_w: float, width: float) -> list[str]:
    """Break `text` into as many lines as it takes to fit `width`.

    Resizing a text box should reflow the words, not shrink them - the same
    thing happens in any word processor. The line count falls out of the
    width rather than being fixed in advance, which is why `break_lines`
    cannot be used directly; once the count is known that function is used to
    even the lines out.
    """
    words = [w for w in text.split() if w]
    if not words or width <= 0:
        return [text] if text else []

    lines, cur = [], []
    for w in words:
        trial = cur + [w]
        px = sum(measure(x) for x in trial) + space_w * (len(trial) - 1)
        if cur and px > width:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur = trial
    if cur:
        lines.append(" ".join(cur))

    if len(lines) > 1:
        even = break_lines(words, [width] * len(lines), measure, space_w)
        if even:
            return even
    return lines


def break_lines(
    words: list[str],
    avail: list[float],
    measure: Callable[[str], float],
    space_w: float,
) -> Optional[list[str]]:
    """Place `words` into exactly len(avail) lines, minimising raggedness.

    DP over (line index, words consumed). Returns None if no assignment fits.
    """
    n, L = len(words), len(avail)
    if n == 0 or L == 0:
        return None

    # w[i][j] = width of words[i:j] on one line
    prefix = [0.0]
    for w in words:
        prefix.append(prefix[-1] + measure(w))

    def line_w(i: int, j: int) -> float:
        return prefix[j] - prefix[i] + space_w * (j - i - 1)

    dp = [[INF] * (n + 1) for _ in range(L + 1)]
    back = [[-1] * (n + 1) for _ in range(L + 1)]
    dp[0][0] = 0.0

    for k in range(L):
        cap = avail[k]
        for i in range(n + 1):
            if dp[k][i] == INF:
                continue
            for j in range(i + 1, n + 1):
                wd = line_w(i, j)
                if wd > cap:
                    break
                slack = (cap - wd) / max(1.0, cap)
                # Every line counts equally. Knuth-Plass leaves the last line
                # free, which is right for justified prose but makes packing
                # cheap; comic typesetting wants a balanced block instead.
                cost = slack * slack
                if k < L - 1:
                    cost += _break_penalty(words[j - 1], words[j] if j < n else "")
                if dp[k][i] + cost < dp[k + 1][j]:
                    dp[k + 1][j] = dp[k][i] + cost
                    back[k + 1][j] = i

    if dp[L][n] == INF:
        return None

    out, j = [], n
    for k in range(L, 0, -1):
        i = back[k][j]
        out.append(" ".join(words[i:j]))
        j = i
    return list(reversed(out))


# ------------------------------------------------------------------ fit search

# Heights in the free space a block may sit at, as a fraction of the slack.
# The centred one is always kept, so it is not in the list.
_DROPS = (0.0, 0.125, 0.25, 0.375, 0.625, 0.75, 0.875, 1.0)


def _placements(rng: "_RowRanges", band_top: float, slack: float, n: int,
                line_h: float, ink_h: float, cfg: "TypesetConfig"):
    """Where down the shape the block may sit - the bands for each option.

    The block used to be nailed to the middle of the available height. In a
    symmetric oval that is exactly right: the chord is widest across the
    centre, so anywhere else is narrower. In anything NOT symmetric it throws
    room away, and the shapes the fitter is handed are very often not
    symmetric - a balloon shared between the two blocks of a split line is cut
    straight across, which leaves each half a wedge. The top half of lee's
    "MY HARD WORK PAID OFF TOO- / -SO TAKE CARE NOW!" balloon runs from a 70px
    chord at its top to 158px at its bottom, and centring a three-line block
    in it measured the lines against ~110px of the ~150px they could have had.
    That is the bulk of why both halves of a split bubble came out small: not
    the scoring, the placement.

    What comes back is the centred block and, when some other height is
    materially roomier, that one too - as CANDIDATES, both scored. Picking the
    roomier one outright is wrong and the sweep says so plainly: `ragged`
    measures how much of its chord a line leaves empty, so handing a layout a
    wider band makes it score WORSE, and choosing on width alone turned "NO
    WAY." from 34pt across two lines into a 27pt one-liner floating in the
    widest part of the bubble. Room is worth having when it buys size and not
    when it only buys air, and the seven terms already know the difference.

    A block that slides to the far end of its half still keeps the full
    vertical gutter between its ink and the cut, several times the gap between
    its own lines, so the two halves of a split bubble still read as two.
    """
    # Every height on offer is measured in ONE pass. The nine of them used to
    # be nine separate trips through the band arithmetic, and eight of those
    # trips were thrown away: only the widths decide which alternative wins,
    # and only the winner's chords are ever read. Asking about all nine at
    # once costs one call instead of nine and answers the same question.
    slack = max(0.0, slack)
    tops = [band_top + slack / 2]
    if slack > 1.0:
        tops += [band_top + slack * f for f in _DROPS]
    # `np.rint` rounds halves to even, which is what Python's `round` does -
    # the band edges land on exactly the rows the scalar loop chose.
    grid = np.asarray(tops, dtype=np.float64)[:, None] \
        + np.arange(n, dtype=np.float64) * line_h
    ya = np.rint(grid).astype(np.int64).ravel()
    yb = np.rint(grid + ink_h).astype(np.int64).ravel()
    w, lo, hi = rng.bands(ya, yb)
    ya_l, yb_l = ya.tolist(), yb.tolist()
    w_l, lo_l, hi_l = w.tolist(), lo.tolist(), hi.tolist()

    def pack(i):
        s = i * n
        return (tops[i],
                list(zip(ya_l[s:s + n], yb_l[s:s + n])),
                [x * cfg.margin for x in w_l[s:s + n]],
                list(zip(lo_l[s:s + n], hi_l[s:s + n])))

    mid = pack(0)
    if slack <= 1.0:
        return [mid]
    # Narrowest band first: it is what caps the longest line, and a placement
    # that buys width on one line by starving another is not roomier. The
    # deadband is what keeps a bubble that is a pixel lopsided from paying for
    # a second candidate it has nothing to gain from.
    best, key = None, (min(mid[2]), sum(mid[2]))
    for i in range(1, len(tops)):
        av = [x * cfg.margin for x in w_l[i * n:(i + 1) * n]]
        k2 = (min(av), sum(av))
        if k2[0] > key[0] * 1.02 or (k2[0] >= key[0] and k2[1] > key[1] * 1.02):
            best, key = i, k2
    return [mid] if best is None else [mid, pack(best)]


def _sweep(cfg) -> tuple:
    """`cfg.leadings` converted for the face this fit is measuring in.

    One place, so the sweep and the score always agree about what a gap is.
    De-duplicated because the clamp collapses the band on an extreme face -
    Anton comes back as (1.00, 1.00, 1.00, 1.00) - and trying the same number
    four times is four times the work for one answer.
    """
    out = []
    for want in cfg.leadings:
        got = round(leading_for(cfg.font_path, want), 3)
        if got not in out:
            out.append(got)
    return tuple(out) or tuple(cfg.leadings)


def _candidates(
    text: str, mask: np.ndarray, size: int, leading: float, cfg: TypesetConfig,
    geom: "Optional[BubbleGeom]" = None, want_features: bool = False,
    fixed: "Optional[list]" = None, size_top: int = 0,
):
    """Yield (score, TextLayout) for every line count that fits at this size.

    With `want_features`, yield (score, TextLayout, terms) instead, `terms`
    being the raw penalty each weight multiplies. Only the tuning bench asks
    for this; the pipeline never does.
    """
    words = text.split()
    if not words:
        return
    path = cfg.font_path
    line_h = size * leading
    if geom is None:
        geom = BubbleGeom(mask)
    if geom.height <= 1:
        return
    v_pad, e_pad = gutters(size, geom.height, cfg)
    # Everything below is measured against the bubble eroded by the gutter, so
    # a line is judged on how close its ink gets to the outline in ANY
    # direction rather than only sideways.
    _, widths, y0, y1 = geom.inset(e_pad)
    rng = geom.ranges(e_pad)
    if y1 <= y0:
        return
    # The erosion has already taken `e_pad` off the top and the bottom; only
    # the part of the vertical gutter that goes beyond it is still owed.
    usable_h = (y1 - y0 + 1) - 2 * max(0.0, v_pad - e_pad)
    # The block is as tall as its INK, not as tall as n line boxes: the top
    # line's ascender gap and the bottom line's descender gap are empty.
    ink_top, ink_bot = ink_extents(path, size, _has_descenders(text))
    ink_h = ink_bot - ink_top
    max_n = min(cfg.max_lines,
                max(1, int((usable_h - ink_h) // line_h) + 1))
    space_w = _text_w(path, size, " ")

    # Every line count, and for each of them every height the block might sit
    # at. The bands are where the ink of each line goes; the anchor the
    # renderer draws at sits `ink_top` above the top of its band.
    band_top = y0 + max(0.0, v_pad - e_pad)

    def _slots():
        for n in range(1, max_n + 1):
            block_h = (n - 1) * line_h + ink_h
            if block_h > usable_h:
                continue
            for top, bands, avail, spans in _placements(rng, band_top,
                                                        usable_h - block_h, n,
                                                        line_h, ink_h, cfg):
                yield n, block_h, top, bands, avail, spans

    def _settle(top, slack, n, used):
        """Slide a block back to the most central height its lines still fit.

        The search over heights above exists to find ROOM: in a wedge - which
        is what half a split balloon is - the widest chords are at one end, and
        a block measured across the middle is measured against width it did not
        have to accept. That is a good way to choose the breaks and a bad way
        to choose where the words end up sitting, and lee's page had "LET'S
        MEET AGAIN." pushed 41% of a half-height above centre and "IS IT
        CATCHING?" 60% below, in balloons with room to spare on the other side.

        So the room is used for what it is worth and then given back. Once the
        lines are broken, their widths are fixed, and every height is asked the
        one question that matters: do THESE lines still fit there? Of the
        heights that say yes, the block takes the one nearest the middle. The
        size and the breaks are untouched - this cannot cost a point of type,
        because a height is only accepted if every line already fits it - and
        the block ends up as central as its own shape allows, which in a
        symmetric bubble is dead centre.

        The bands are then re-measured where the block actually sits, so the
        score is computed on the layout that is drawn rather than on the one
        that was used to choose the breaks.
        """
        centre = band_top + slack / 2
        if slack <= 1.0 or abs(top - centre) <= 0.5:
            return None
        lo, hi = band_top, band_top + slack
        ts = np.arange(np.floor(lo), np.ceil(hi) + 1.0, dtype=np.float64)
        ts = np.unique(np.concatenate([np.clip(ts, lo, hi), (centre, top)]))
        grid = ts[:, None] + np.arange(n, dtype=np.float64) * line_h
        ya = np.rint(grid).astype(np.int64).ravel()
        yb = np.rint(grid + ink_h).astype(np.int64).ravel()
        w, lo_x, hi_x = rng.bands(ya, yb)
        w_l = w.tolist()
        av = np.asarray([x * cfg.margin for x in w_l],
                        dtype=np.float64).reshape(len(ts), n)
        ok = np.flatnonzero((av >= np.asarray(used, dtype=np.float64)).all(1))
        if not ok.size:
            return None                  # cannot happen: `top` itself fits
        pick = int(ok[np.argmin(np.abs(ts[ok] - centre))])
        if abs(ts[pick] - top) < 1e-9:
            return None
        s = pick * n
        ya_l, yb_l = ya.tolist(), yb.tolist()
        return (list(zip(ya_l[s:s + n], yb_l[s:s + n])),
                av[pick].tolist(),
                list(zip(lo_x.tolist()[s:s + n], hi_x.tolist()[s:s + n])))

    for n, block_h, top, bands, avail, spans in _slots():
        if min(avail) <= 0:
            continue

        if fixed is not None:
            # The breaks are already decided - somebody typed them. All that is
            # left to choose is where the block sits, and that is chosen by the
            # same scoring as a fresh fit, so a hand-broken block lands exactly
            # where the fitter would have put those same lines.
            if len(fixed) != n:
                continue
            lines = list(fixed)
            if any(_text_w(path, size, ln) > a for ln, a in zip(lines, avail)):
                continue
        else:
            lines = break_lines(words, avail, lambda s: _text_w(path, size, s),
                                space_w)
            if lines is None:
                continue

        used = [_text_w(path, size, ln) for ln in lines]
        settled = _settle(top, usable_h - block_h, n, used)
        if settled is not None:
            bands, avail, spans = settled

        # Every line is scored, the last one at a discount. Prose typesetting
        # lets the last line run short for free, and that is what used to let
        # "DON'T WORRY / ABOUT IT - / REALLY." come out as four one-word
        # lines: the ugly stub at the bottom cost nothing. A reader sees the
        # block, not the sentence, so the whole block is what gets judged -
        # discounted at the end, because some slack there is normal.
        wts = [1.0] * n
        if n > 1:
            wts[-1] = cfg.w_last_line
        tot_w = sum(wts)

        core = [1 - u / a for u, a in zip(used, avail)]
        ragged = sum(w * c * c for w, c in zip(wts, core)) / tot_w

        # Raggedness alone is measured against each line's OWN chord, and in an
        # oval that lets a tall stack cheat: every line of "DON'T / WORRY /
        # ABOUT IT - / REALLY." fills its own narrow band near the poles, so it
        # scores as tidy while looking like a column. Compare the lines to each
        # other as well - a typesetter judges the SHAPE of the block, and wants
        # the lines close to the same length.
        w_long = max(used) or 1.0
        imbalance = sum(w * ((w_long - u) / w_long) ** 2
                        for w, u in zip(wts, used)) / tot_w

        # A one-word line is an orphan when it is short next to the rest of the
        # block. Measuring it against its own chord instead is what let the
        # column layout through: near the poles of an oval the chord is narrow,
        # so a single word "filled" its line. "UNBELIEVABLE" alone in a bubble
        # is not an orphan, and neither is a one-line layout.
        # A stub is only an orphan if some OTHER line holds more than one word
        # - that is the line it could have been joined to. When every line is a
        # single word the breaking had no choice: "HELLO, / EVERYONE!" is two
        # words and two lines, and there is no arrangement of it that is not
        # one word per line. Charging it as two orphans was what made the
        # fitter prefer "HELLO, EVERYONE!" as one 14pt ribbon across a 190px
        # balloon, and no weighting could fix that while still calling a real
        # column of stubs bad. What is wrong with a stack like "SO. / WE /
        # NEED / TO / TALK." is the SIZE that forced it, and `w_small` and
        # `w_cpl` are the terms that price that.
        joinable = any(len(ln.split()) > 1 for ln in lines)
        orphans = 0.0 if (n == 1 or not joinable) else sum(
            w for w, ln, u in zip(wts, lines, used)
            if len(ln.split()) == 1 and u < 0.65 * w_long) / tot_w

        # How little of the bubble's height the block covers - but only once it
        # covers less than `vfill_target` of it, and zero above that.
        #
        # This was `1 - block_h/usable_h`: a straight reward for filling more
        # paper, positive for every layout, which meant it doubled as a general
        # "bigger is better" pressure on top of `small` and so had to stay weak
        # (0.85) to avoid shredding good blocks into one-word columns. Weak is
        # exactly what it could not afford to be. Measured across the eight
        # balloons lee marked up, the difference between the layout he rejected
        # in a tall narrow bubble and the one he approved in a wide one is
        # componentwise non-negative on all seven terms - so NO reweighting of
        # them, at any values, ranks both the way he does. The monotone shape
        # is what forbids it: any weight big enough to lift a starved block
        # also lifts a comfortable one.
        #
        # A ramp fixes that, and says something a typesetter would recognise
        # instead of something the optimiser wanted: a block has to sit IN its
        # balloon, and below about a third of the height it stops reading as
        # typesetting in a bubble and starts reading as a ribbon floating in an
        # ocean of white. Above that line the layout is fine and the term has
        # no opinion - how big to go from there is `small`'s question, and
        # "don't crowd the bubble" is the gutter's. It is priced steeply (10.0)
        # because it is a floor, not a preference; on a well-filled block it
        # contributes nothing at all.
        #
        # A matching width term lived here for a while, to catch the opposite
        # failure: a narrow COLUMN of one-word lines, which `ragged` calls tidy
        # because each stub fills its own narrow band near the poles of the
        # oval. It is gone, and the reason is worth recording. Once `orphans`
        # stopped firing on breaks that had no alternative (see above), the LP
        # over these terms could satisfy every specimen without it, and the
        # best margin over a layout a typesetter would reject was very slightly
        # WIDER with the width term deleted than with it free to help. What
        # actually prices the column is `w_balance` and `w_cpl`: its stubs are
        # both uneven against each other and far under the comfortable line
        # length. A term the data will not pay for is a term that will
        # misbehave on the bubble it was never measured against.
        fill = block_h / max(1.0, usable_h)
        tgt = max(1e-6, cfg.vfill_target)
        vfill = max(0.0, (tgt - fill) / tgt)
        # How small this is - measured against the sizes THIS balloon can
        # actually take, not against the settings dialog.
        #
        # It used to divide by `max_font - min_font`, and that is what left
        # page 8 under-set. lee runs 10-34, so in a small balloon whose text
        # cannot exceed 16pt no matter how it breaks, the whole live ladder is
        # 10..16 and the step from 14 to 16 - a third of everything on offer -
        # registered as 8% of a 24pt span, about 0.29 of score. Any layout at
        # 14 that broke a shade more evenly than the one at 16 bought the
        # smaller type for less than it was worth, and "PLEASE, LISTEN TO WHAT
        # THIS CHILD HAS TO SAY." sat at 14 in the bottom half of a balloon
        # with room to spare. The ceiling the settings allow is not a fact
        # about the bubble; the largest size that fits is, so that is the top
        # of the ladder and the top of the ladder costs nothing.
        top = float(size_top) if size_top else float(cfg.max_font)
        span = max(1.0, top - cfg.min_font)
        small = min(1.0, max(0.0, 1 - (size - cfg.min_font) / span))

        # Short lines are the main tell of automated typesetting. Penalise lines
        # below the comfortable length hard, above it only gently - the chord
        # width already caps how long a line can get.
        # The target is the comfortable length, unless the text is shorter than
        # that or the bubble is too narrow to hold it. It deliberately does NOT
        # depend on the line count: dividing the text by n made the target
        # collapse as lines were added, so any number of lines looked "on
        # target" and nine one-word lines cost nothing.
        avg_ch = _text_w(path, size, "ABCDEFGHIJKLMNOPQRSTUVWXYZ ") / 27.0
        target = max(4.0, min(float(cfg.ideal_cpl), float(len(text)),
                              max(avail) / max(1.0, avg_ch)))
        cpl_pen = 0.0
        for w, ln in zip(wts, lines):
            d = (len(ln) - target) / target
            cpl_pen += w * (d * d if d < 0 else 0.15 * d * d)
        cpl_pen /= tot_w

        # An oval bubble makes narrow top/bottom chords, so a 9-line stack of
        # one-word lines scores as "well filled". Penalise the stack directly.
        #
        # But "too many lines" is relative to how much there is to typeset. Five
        # is plenty for a sentence and miserly for a paragraph: held at a flat
        # five, a seventy-character line of dialogue was forced onto four long
        # lines at 12pt inside a balloon that had room for seven at 19pt, which
        # is the opposite of the failure this whole model exists to fix. So the
        # cap is a floor, and past it another line is allowed for every
        # `relax_cpl` characters - the point being that lines never have to get
        # shorter than that to buy the extra line. Raising the flat cap instead
        # does fix the long sentences, and it also turns "MY HARD WORK PAID OFF
        # TOO-" into six stubs; the length term is what tells those apart.
        #
        # Both of those count characters, and a count of characters knows
        # nothing about the BALLOON. In a tall narrow bubble a lot of short
        # lines is not a stack, it is the shape doing what it was drawn to do,
        # and holding it to the same five-line budget as a wide oval is what
        # stranded "PLEASE, LISTEN TO WHAT THIS CHILD HAS TO SAY." at 14pt in
        # a 95x205 balloon that takes it at 16 across seven. So the budget also
        # gets the lines the shape affords: how many rows of type stand in the
        # usable height, discounted because the top and bottom of a rounded
        # bubble are too narrow to typeset right across.
        #
        # This cannot be spent on an arbitrarily large size, because the rows
        # are counted in line heights: double the size and half as many fit.
        # All it says is that a bubble twice as tall as a round one may hold
        # twice the lines before anybody calls it a stack.
        rows = usable_h / max(1.0, line_h)
        soft = max(float(cfg.soft_max_lines), len(text) / cfg.relax_cpl,
                   rows * cfg.rows_afforded)
        stack = (n / soft) ** 2 if n > soft else 0.0

        score = (cfg.w_lines * stack + cfg.w_ragged * ragged
                 + cfg.w_balance * imbalance + cfg.w_orphan * orphans
                 + cfg.w_vfill * vfill
                 + cfg.w_small * small + cfg.w_cpl * cpl_pen)

        # The renderer draws with an "mm" anchor, so the origin is the anchor
        # point, not the top of the ink: back it off by `ink_top`. Doing the
        # arithmetic on the ink is what optically centres all-caps typesetting
        # inside the bubble instead of hanging it off the descender line.
        #
        # Every line of the block sits on ONE axis. Centring each on its own
        # chord instead is defensible in a circle, where every chord shares a
        # centre and the answer is the same either way - and it is what put
        # lee's narration blocks down the page as a staircase, one step per
        # line, because the shape they were measured in was the ragged
        # outline of the Japanese they replace and no two of its chords agree.
        # A block of text has one centre, and it is read off the lines the
        # break actually produced, so the words that fitted their bands still
        # fit them.
        cxi = int(round(line_axis(spans, used)))
        origins = [(cxi, int(round(ya - ink_top))) for (ya, yb) in bands]

        layout = TextLayout(
            lines=lines, font_size=size, leading=leading,
            line_origins=origins, score=score, font_path=path,
        )
        if want_features:
            # The score is a linear combination of these seven and nothing
            # else, so handing them out lets the bench ask whether ANY set of
            # weights ranks the layouts the way a typesetter would - a question
            # no amount of scanning the weights can answer.
            yield score, layout, dict(
                stack=stack, ragged=ragged, imbalance=imbalance,
                orphans=orphans, vfill=vfill, small=small,
                cpl_pen=cpl_pen)
        else:
            yield score, layout


def _feasible_top(text, mask, cfg: TypesetConfig, geom) -> int:
    """The largest size at which this text fits in this shape at all.

    Walked from the top down and stopped at the first size that yields
    anything, so the sizes it touches are exactly the ones that do not fit -
    which bail out early and cost almost nothing. It is the top of the ladder
    `small` is measured on: how small a layout is only means something next to
    how big this balloon would ever have let it be.
    """
    sweep = _sweep(cfg)
    for size in range(cfg.max_font, cfg.min_font - 1, -cfg.font_step):
        for leading in sweep:
            for _ in _candidates(text, mask, size, leading, cfg, geom):
                return size
    return cfg.min_font


def _best(text: str, mask: np.ndarray, cfg: TypesetConfig) -> Optional[TextLayout]:
    """The best-scoring layout over every size and leading the settings allow.

    The ladder is walked from the top down and cut short, which is worth being
    precise about because it must not change the answer. Every one of the seven
    scoring terms is non-negative, so a layout's score is never less than its
    `small` term alone; and `small` depends on nothing but the size, falling as
    the size rises. So `w_small * small(size)` is a floor under EVERY layout at
    that size and at every size below it. Once that floor reaches the best
    score already in hand, nothing further down the ladder can beat it, and the
    rest of the walk is arithmetic whose answer is already known. On page 8's
    "LET'S MEET AGAIN." the winner is 21pt scoring 0.380 and the floor passes
    it at 19pt: three sizes are typeset instead of twenty-five.

    Sizes ABOVE `_feasible_top` are skipped for the same reason and with more
    certainty - `_feasible_top` just walked them and none of them fitted.
    """
    best_score, best = INF, None
    geom = BubbleGeom(mask)          # the distance transform, once for all sizes
    top = _feasible_top(text, mask, cfg, geom)
    sweep = _sweep(cfg)
    span = max(1.0, float(top) - cfg.min_font)
    for size in range(top, cfg.min_font - 1, -cfg.font_step):
        floor = cfg.w_small * min(1.0, max(0.0, 1 - (size - cfg.min_font) / span))
        if floor >= best_score:
            break
        for leading in sweep:
            for score, lay in _candidates(text, mask, size, leading, cfg, geom,
                                          size_top=top):
                if score < best_score:
                    best_score, best = score, lay
    return best


def place_lines(lines, mask, cfg: TypesetConfig, size: int, leading: float,
                path: str = "") -> "Optional[list]":
    """Where the fitter would put these exact lines in this exact shape.

    The fitter centres every line on the balloon's own chord at that line's
    height and centres the block on the paper inside the outline. Anything
    that rebuilds a layout some other way - centring in the bounding
    rectangle, say - puts the same words somewhere else, and the difference is
    visible the moment the two paths swap over. This is the one place that
    arithmetic lives, so they cannot drift apart.

    Returns the line origins, or None when the lines will not fit this shape
    at this size (the caller then falls back to its own placement).
    """
    lines = [l for l in (lines or []) if l.strip()]
    if not lines or mask is None:
        return None
    m = mask > 0
    if not m.any():
        return None
    if path and path != cfg.font_path:
        cfg = replace(cfg, font_path=path)
    best_score, best = INF, None
    for score, lay in _candidates(" ".join(lines), m, int(size), float(leading),
                                  cfg, fixed=lines):
        if score < best_score:
            best_score, best = score, lay
    return list(best.line_origins) if best is not None else None


def _box_of(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return (0, 0, 1, 1)
    return (int(xs.min()), int(ys.min()),
            int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))


def _plain_fit(text: str, mask: np.ndarray, cfg: TypesetConfig
               ) -> Optional[TextLayout]:
    """Last resort: wrap into the box as a plain rectangle, shrinking as far
    as the absolute floor. Ugly beats spilling outside the bubble.

    The sweep starts at `min_font` and only goes down, which looks timid and
    is not. Starting it at `max_font` and keeping any size whose every line
    lands on paper the mask owns was tried, on page 8's "HOW RUDE OF THEM..."
    - the one region on that page still typesetting at the floor. It changed
    nothing: the white gap it sits in is 59px at its widest and ragged down
    the right where the art cuts in, so no size above the floor gets a line
    inside it. What is wrong with that region is not its size but that it is
    free text on art being held inside a sliver of background; the box it
    should typeset in is bigger than the white the detector handed it.

    It wraps on the AUTHOR'S breaks, not on spaces - the same rule and the
    same three lines as `_spill_fit`. Every path above this one already breaks
    at a dash or a row of dots before it shrinks anything; this one did not,
    and it is the only one that shrinks past the legibility floor. So
    GLOW-SAN! - one word, nothing to wrap on - came out as a single line at
    7pt in a box that had room for GLOW- over SAN! at the minimum. Making the
    type illegible to avoid a line break the author himself wrote in is the
    wrong way round. lee: *"all box type shoud do the line break thing wjhen
    the text is too small"*.
    """
    toks, glue = author_break_tokens(text)
    if not toks:
        return None
    path = cfg.font_path
    bx, by, bw, bh = _box_of(mask)
    avail_w = bw * cfg.margin

    for size in range(cfg.min_font, cfg.absolute_floor - 1, -1):
        # Use the ink height rather than full font metrics: ascent+descent
        # carries a lot of padding, and at this point we are fighting for
        # every pixel inside the box.
        #
        # But never under MIN_LEADING. This is the FITTER choosing, and the
        # floor binds every automatic answer - the docstring on MIN_LEADING
        # names this very path and it did not honour it: it set `leading=1.0`
        # and packed the lines at the ink height, which is the tight grey mass
        # the floor exists to prevent. lee, looking at his own page:
        # *"trhe nimimun line gap is not ebeing enforced ty the typesetter"*.
        # The way out of a box this cramped is a smaller size, not a smaller
        # gap - and the sweep below is already walking the sizes down.
        ink_h = _font(path, size).getbbox("Ahgjy")[3]
        lh = max(float(size) * MIN_LEADING, ink_h * 0.95)
        lines, cur = [], ""
        ok = True
        for k, tk in enumerate(toks):
            # A piece that follows a dash rejoins with NO space - GLOW- SAN!
            # with a space in it is not a word anybody wrote.
            trial = tk if not cur else (cur + tk if glue[k] else cur + " " + tk)
            if _text_w(path, size, trial) <= avail_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = tk
            if _text_w(path, size, cur) > avail_w:
                ok = False          # one unbreakable piece is wider than the box
                break
        if not ok:
            continue
        if cur:
            lines.append(cur)
        if len(lines) * lh > bh:
            continue

        top = by + (bh - len(lines) * lh) / 2
        origins = [(int(bx + bw / 2), int(round(top + (i + 0.5) * lh)))
                   for i in range(len(lines))]
        # The gap that was actually used, not a fixed 1.0. The panel shows this
        # number and a person adjusts from it, so a layout that reports a gap
        # it is not using hands them the wrong starting point.
        return TextLayout(lines=lines, font_size=size,
                          leading=round(lh / max(1, size), 3),
                          line_origins=origins, font_path=path, fit_ok=False)
    return None


def _spill_fit(text: str, mask: np.ndarray, cfg: TypesetConfig
               ) -> Optional[TextLayout]:
    """Set it at the minimum size and let it run outside the box.

    For **outside text and sound effects only**. The box round a line of free
    text is where the Japanese ink was, and Japanese runs down the page in a
    narrow column: the English runs across, so the box is routinely the wrong
    shape for the words rather than the wrong size. Squeezing the English into
    it means 8pt type on a 1365px page, which is not typesetting, it is a
    footnote. And there is no balloon here - the words sit on artwork, where a
    typesetter would simply set them bigger and let them cover the drawing.

    lee: *"outside text and sfx shoud be able to got outside teh box if the
    text size is bellow the miimum"*.

    So: `min_font`, never below, wrapped to the box's own width where it can
    and past it where it cannot, centred on the box so it spills evenly rather
    than growing off one side. Inside a balloon this would be wrong - the
    paper is the limit and `_plain_fit` still holds there.

    Spilling is the LAST thing tried, not the first, and it still takes every
    line break the text offers before it takes any artwork. lee, with
    LITTLE VILLAINESS-IN-TRAINING. laid across a panel in one strip: *"shou
    create new line if its too big for the box"*. Wrapping on spaces alone
    left that as a single 23-character word nothing could break, so it went
    out sideways over the drawing when it could have been four lines standing
    in the box. It breaks where the author already put a dash - the same rule,
    and the same code, as `_fit_on_author_breaks` above.
    """
    if not text.split():
        return None
    path, size = cfg.font_path, cfg.min_font
    bx, by, bw, bh = _box_of(mask)
    # Wrap to the box's width, and never mind if one piece is wider than that:
    # the whole point here is that the block may be wider than the box.
    avail_w = max(1.0, bw * cfg.margin)
    ink_h = _font(path, size).getbbox("Ahgjy")[3]
    lh = max(float(size) * MIN_LEADING, ink_h * 0.95)
    toks, glue = author_break_tokens(text)
    lines, cur = [], ""
    for k, tk in enumerate(toks):
        # A piece that follows a dash rejoins with NO space - GLOW- SAN! with
        # a space in it is not a word anybody wrote.
        trial = tk if not cur else (cur + tk if glue[k] else cur + " " + tk)
        if _text_w(path, size, trial) <= avail_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = tk
    if cur:
        lines.append(cur)
    # Centred on the BOX, not hung off its top-left, so the overflow is shared
    # between the two sides instead of all landing on one.
    cx, cy = bx + bw / 2.0, by + bh / 2.0
    top = cy - len(lines) * lh / 2.0
    origins = [(int(round(cx)), int(round(top + (i + 0.5) * lh)))
               for i in range(len(lines))]
    return TextLayout(lines=lines, font_size=size,
                      leading=round(lh / max(1, size), 3),
                      line_origins=origins, font_path=path,
                      fit_ok=True, spills=True)


def balloon_lobes(mask: np.ndarray, glyph: "Optional[np.ndarray]") -> list:
    """The two lobes of a double balloon, or nothing.

    The same reading of the outline the detector does - a dent facing a dent is
    a neck, and a chord between them divides the balloon - asked here of a
    balloon that arrived as ONE region. A chapter found before the detector
    could see necks is full of those, and re-running Find text on it would
    throw away every translation on the page; this reads the neck off the
    shape at typesetting time instead, so an old chapter letters like a new one.
    """
    if glyph is None:
        return []
    try:
        from .detect.classical import OutlineConfig, _neck_split
    except Exception:
        return []
    m = (mask > 0).astype(np.uint8) * 255
    g = _typesetting_ink(m, glyph)
    try:
        return _neck_split(m, g, OutlineConfig())
    except Exception:
        return []


def _typesetting_ink(shape: np.ndarray, glyph: np.ndarray) -> np.ndarray:
    """The typesetting inside a balloon, with the balloon's own outline dropped.

    A page reloaded from disk has no saved masks: `region_from_record` rebuilds
    the ink as `(gray <= INK) & (bubble > 0)` off a polygon that traces the
    balloon's OUTER edge - so the dark RIM of the balloon comes back as ink
    too. That ring hugs the waist from both sides and hides the neck, which is
    why a double balloon typeset as one blob after a reload but not before.
    A rim runs along the border; a letter sits inside it. So each blob of ink
    is kept only if most of it survives eroding the balloon a little.
    """
    m = (shape > 0).astype(np.uint8)
    g = ((glyph > 0) & (m > 0)).astype(np.uint8)
    if not g.any():
        return g
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    inner = cv2.erode(m, ker, iterations=2)
    n, lab = cv2.connectedComponents(g, connectivity=8)
    # Both counts come from one pass over the labels. Testing `lab == i` blob by
    # blob walked the whole page once per blob, and a busy balloon has forty.
    flat = lab.ravel()
    tot = np.bincount(flat, minlength=n).astype(np.float64)
    deep = np.bincount(flat, weights=(inner > 0).ravel().astype(np.float64),
                       minlength=n)
    share = np.divide(deep, tot, out=np.zeros_like(tot), where=tot > 0)
    keep = (tot > 0) & (share >= 0.6)
    keep[0] = False                      # label 0 is the background
    return keep[lab].astype(g.dtype)


def _fit_into(text: str, shape: np.ndarray, cfg: TypesetConfig
              ) -> Optional[TextLayout]:
    return _best(text, shape > 0, cfg) or _plain_fit(text, shape > 0, cfg)


def _two_lobe_fit(region: TextRegion, text: str, mask: np.ndarray,
                  cfg: TypesetConfig, whole: Optional[TextLayout]
                  ) -> Optional[TextLayout]:
    """One speech, two lobes: each half in its own lobe, both the same size.

    A balloon drawn as two overlapping ovals holds ONE sentence written across
    the waist, and typesetting it as a single paragraph runs the middle lines
    straight through the pinch - so the fitter shrinks the whole speech until
    the widest line clears the narrowest part. That is why lee's double
    balloons came out tiny.

    A typesetter does the obvious thing instead: the first part of the sentence
    fills the first lobe, the rest fills the second, and both are typeset at
    one size so it still reads as one voice. Which word the break falls on is
    chosen by the lobes' own areas and then nudged either way. If the balloon
    has a neck, the division happens - the shape of the balloon decides, not
    the length of this particular sentence, so the same balloon always letters
    the same way.

    No word is ever split, and every word goes in: the break is a space.
    """
    words = text.split()
    if len(words) < 4:
        return None                     # too short to be worth dividing
    lobes = balloon_lobes(mask, region.text_mask)
    if len(lobes) < 2:
        return None
    (sa, _), (sb, _) = lobes[0], lobes[1]
    aa, ab = float((sa > 0).sum()), float((sb > 0).sum())
    if aa <= 0 or ab <= 0:
        return None

    # Where the sentence probably breaks: in proportion to the room. Then a
    # couple of words either side, because a word is a lumpy unit and the
    # nearest space to the ideal split is not always the best one.
    lens = [len(w) + 1 for w in words]
    total = float(sum(lens))
    want = total * aa / (aa + ab)
    run, guess = 0.0, 1
    for i, ln in enumerate(lens):
        if run + ln / 2.0 >= want:
            guess = max(1, i)
            break
        run += ln
    else:
        guess = len(words) - 1

    best = None
    seen = set()
    for i in range(max(1, guess - 2), min(len(words), guess + 3)):
        if i in seen:
            continue
        seen.add(i)
        a = _fit_into(" ".join(words[:i]), sa, cfg)
        b = _fit_into(" ".join(words[i:]), sb, cfg)
        if a is None or b is None:
            continue
        size = min(int(a.font_size), int(b.font_size))
        # Break as evenly as the room allows: two lobes of similar size
        # holding wildly uneven halves reads as a mistake even when it fits.
        skew = abs(sum(lens[:i]) / total - aa / (aa + ab))
        key = (size, -skew)
        if best is None or key > best[0]:
            best = (key, i, size)
    if best is None:
        return None
    _, split, size = best
    # The division is NOT a size optimisation, and treating it as one is what
    # made it inconsistent. "Only divide when it typesets bigger" is a rule
    # about the sentence, not about the balloon: the same balloon drawn twice
    # on one page divides under a long line and merges under a short one, and
    # a reader cannot see any reason for the difference. A balloon with a neck
    # in it is TWO places to put words, and a typesetter puts words in both,
    # every time. So the only thing left that can refuse the division is
    # readability - if dividing drops the type under the floor a human has to
    # check while merged clears it, merged wins, because too small to read is
    # worse than run together.
    if size < cfg.min_font and whole is not None \
            and int(whole.font_size) >= cfg.min_font:
        return None

    # Both lobes re-typeset at the one size they can share, and each handed
    # the box it occupies - the same re-description every other block gets, so
    # a lobe on its own is an ordinary paragraph in an ordinary box.
    one = replace(cfg, min_font=size, max_font=size,
                  absolute_floor=min(size, cfg.absolute_floor))
    a = _fit_into(" ".join(words[:split]), sa, one)
    b = _fit_into(" ".join(words[split:]), sb, one)
    if a is None or b is None or not a.lines or not b.lines:
        return None
    a = anchor_to_frame(a, one)
    b = anchor_to_frame(b, one)
    if not a.frame or not b.frame:
        return None
    lines = list(a.lines) + list(b.lines)
    origins = [tuple(o) for o in a.line_origins] + \
              [tuple(o) for o in b.line_origins]
    if len(origins) != len(lines):
        return None
    # One box round the pair, so dragging the speech moves both halves and the
    # browser has something to draw a frame on. The line positions inside it
    # are `fixed`: they are two blocks, not one evenly-spaced stack.
    ax, ay, aw, ah = a.frame
    bx, by, bw, bh = b.frame
    x0, y0 = min(ax, bx), min(ay, by)
    frame = (int(x0), int(y0),
             int(max(ax + aw, bx + bw) - x0),
             int(max(ay + ah, by + bh) - y0))
    return TextLayout(lines=lines, font_size=size,
                      leading=max(MIN_LEADING, float(a.leading or 0)),
                      line_origins=[(int(x), int(y)) for x, y in origins],
                      font_path=cfg.font_path, fit_ok=bool(a.fit_ok
                                                           and b.fit_ok),
                      score=float(a.score + b.score), frame=frame,
                      fixed=True)


def pull_to_box(region: TextRegion, lay: TextLayout, cfg: TypesetConfig,
                mask: "Optional[np.ndarray]" = None) -> TextLayout:
    """Move a block back over its own box, as far as its share allows.

    Only for a block that SHARES a balloon. A block alone in one is typeset
    into the balloon on purpose - that is what makes it big and centred, and
    dragging it onto the narrow column the Japanese stood in would undo it.

    Two blocks in one balloon are a different question. Each is fitted into
    its own share, and a share cut at the neck of a waisted balloon can be far
    wider than the box inside it, so the words come out centred on the LOBE
    and not on the box: on lee's page HUH!? began a good thirty pixels left of
    the box it belongs to, with the box's own right-hand side empty.
    lee: *"the typesetting shoud not be putting text across 2 boxes ... make it
    so that teh text goes where teh box is"*, and then, over a picture of it
    still happening: *"this is still happening look into it"*.

    Nothing here re-fits, so nothing here costs a point of size - trimming the
    share does, and on a balloon whose boxes are narrow Japanese columns it
    costs half of it. The block keeps the size the share bought it and is
    simply carried over to where it belongs, by the largest fraction of the
    way that keeps every line on the paper.
    """
    if not lay.lines or not lay.line_origins or lay.fixed:
        return lay
    if mask is None:
        mask = region.place_mask()
    if mask is None:
        return lay
    m = mask > 0
    if not m.any():
        return lay
    H, W = m.shape[:2]
    x, y, w, h = (float(v) for v in region.bbox)
    tx, ty = x + w / 2.0, y + h / 2.0
    xs = [p[0] for p in lay.line_origins]
    ys = [p[1] for p in lay.line_origins]
    cx = sum(xs) / float(len(xs))
    cy = (min(ys) + max(ys)) / 2.0
    dx, dy = tx - cx, ty - cy
    if abs(dx) < 1.0 and abs(dy) < 1.0:
        return lay
    f = _font(lay.font_path or cfg.font_path, lay.font_size)
    halves = [f.getlength(t) / 2.0 for t in lay.lines]
    hh = lay.font_size * 0.5
    # Every row's chord, once, so "does this line still stand in the shape"
    # is two comparisons per row instead of a walk along the line.
    _rows, _first, _last = _row_chords(m)

    def fits(t: float) -> bool:
        """Is the WHOLE of every line inside the mask at this fraction?

        It used to be nine samples per line - the two ends and the middle, at
        three heights - and nine samples is not a line. A block can pass all
        nine and still have its first letter standing in a notch the samples
        step over, which is what happened to lee's page 001: the fitter had
        set the balloon dead straight, `pull_to_box` slid it seven pixels left
        towards the box, and REGION lost its R to a mask edge no sample was
        taken at. The line came out as 'EGION and nothing in the pipeline knew
        a letter was missing.

        A line occupies every row of its band and every column between its
        ends, so that is what gets asked: across the rows it covers, the
        mask's own chord has to reach past both ends of it.
        """
        for (ox, oy), hw in zip(lay.line_origins, halves):
            nx, ny = ox + dx * t, oy + dy * t
            ya = int(round(ny - hh))
            yb = int(round(ny + hh)) + 1
            if ya < 0 or yb > H:
                return False
            if not _rows[ya:yb].all():
                return False
            if _first[ya:yb].max() > nx - hw or _last[ya:yb].min() < nx + hw:
                return False
        return True

    if fits(1.0):
        best = 1.0
    else:
        best, lo, hi = 0.0, 0.0, 1.0
        for _ in range(12):
            mid = (lo + hi) / 2.0
            if fits(mid):
                best, lo = mid, mid
            else:
                hi = mid
    if best <= 0.02:
        return lay
    lay.line_origins = [(int(round(ox + dx * best)), int(round(oy + dy * best)))
                        for ox, oy in lay.line_origins]
    return lay


def keep_on_page(lay: TextLayout, cfg: TypesetConfig,
                 shape: "tuple") -> TextLayout:
    """Slide a spilling block back until it is on the paper.

    Leaving the box is the point; leaving the PAGE is not. A block allowed to
    run past its own box can run past the edge of the scan too, and typesets
    outside the image are not typesetting - they are gone, with nothing on the
    page to say a word is missing. This only ever SLIDES: the size, the breaks
    and the angle are already settled, and a block wider than the whole page
    is left where it is because there is nowhere to put it.
    """
    if not lay.lines or not lay.line_origins:
        return lay
    H, W = int(shape[0]), int(shape[1])
    path = lay.font_path or cfg.font_path
    # A sound effect is drawn at an angle, and a turned line reaches further
    # sideways than its own width: the corner of the box round it is what
    # crosses the edge of the page first. CLACK went off lee's right margin
    # measured as though it were level.
    rot = math.radians(float(getattr(lay, "rotate", 0.0) or 0.0))
    c, sn = abs(math.cos(rot)), abs(math.sin(rot))
    hh = lay.font_size * 0.6
    ext = [(((_text_w(path, lay.font_size, ln) * c) + 2 * hh * sn) / 2.0,
            ((_text_w(path, lay.font_size, ln) * sn) + 2 * hh * c) / 2.0)
           for ln in lay.lines]
    left = min(x - ew for (x, _), (ew, _) in zip(lay.line_origins, ext))
    right = max(x + ew for (x, _), (ew, _) in zip(lay.line_origins, ext))
    top = min(y - eh for (_, y), (_, eh) in zip(lay.line_origins, ext))
    bot = max(y + eh for (_, y), (_, eh) in zip(lay.line_origins, ext))
    dx = dy = 0.0
    if right - left <= W:
        dx = max(0.0, -left) - max(0.0, right - W)
    if bot - top <= H:
        dy = max(0.0, -top) - max(0.0, bot - H)
    if abs(dx) < 1.0 and abs(dy) < 1.0:
        return lay
    lay.line_origins = [(int(round(x + dx)), int(round(y + dy)))
                        for x, y in lay.line_origins]
    if lay.frame:
        fx, fy, fw, fh = lay.frame
        lay.frame = (int(round(fx + dx)), int(round(fy + dy)), fw, fh)
    return lay


def enforce_bounds(region: TextRegion, lay: TextLayout,
                   cfg: TypesetConfig,
                   mask: "Optional[np.ndarray]" = None) -> TextLayout:
    """Guarantee every line sits inside the balloon - not inside its bounding box.

    Origins are centres (the renderer draws with an "mm" anchor), so a line is
    inside when its half-width and half-height fit either side of its origin.
    Anything that cannot be made to fit is clamped rather than allowed to
    spill over the artwork.

    The width a line is allowed is the chord of the balloon ACROSS THAT LINE,
    not the width of the rectangle drawn round the whole balloon. On a spiky,
    cloud or wobbly outline those are wildly different numbers: the bounding
    box of a burst balloon reaches out to the tips of the spikes, so a line
    clamped to it can sit almost entirely on the artwork and still count as
    "inside". That is the overflow you can see on the page.

    The box has to be the same shape the layout was fitted to, so `mask` comes
    through here as well: clamping a re-cut half of a split balloon back into
    the half it was detected with would undo the re-cut line by line.
    """
    if mask is None:
        mask = region.place_mask()
    if mask is None or not lay.lines:
        return lay
    # A block that is bigger than its region ON PURPOSE - outside text or a
    # sound effect set at the minimum rather than shrunk under it. Clamping
    # every line into the region would undo the spill in the same breath it
    # was made, and what it actually does is stack all fourteen lines on the
    # one row that fits. lee: *"outside text and sfx shoud be able to got
    # outside teh box if the text size is bellow the miimum"*.
    if getattr(lay, "spills", False):
        return lay
    m = mask > 0
    bx, by, bw, bh = _box_of(m)
    path = lay.font_path or cfg.font_path
    f = _font(path, lay.font_size)
    asc, desc = f.getmetrics()
    half_h = (asc + desc) / 2

    fixed = []
    for (cx, cy), line in zip(lay.line_origins, lay.lines):
        half_w = _text_w(path, lay.font_size, line) / 2
        # Vertical first: the chord to measure is the one at the line's final
        # height, so the line has to be brought inside top-to-bottom before
        # there is a meaningful chord to ask about.
        ny = min(max(cy, by + half_h), by + bh - half_h)
        if half_h * 2 > bh:
            ny = by + bh / 2
            lay.fit_ok = False
        lo, hi = _chord_at(m, ny - half_h, ny + half_h)
        if hi <= lo:                        # nothing of the balloon on this row
            lo, hi = bx, bx + bw - 1
        span = hi - lo + 1
        if half_w * 2 > span:               # wider than the balloon even so
            nx = (lo + hi) / 2
            lay.fit_ok = False
        else:
            nx = min(max(cx, lo + half_w), hi + 1 - half_w)
        fixed.append((int(round(nx)), int(round(ny))))
    lay.line_origins = fixed
    return lay


def anchor_to_frame(lay: TextLayout, cfg: TypesetConfig) -> TextLayout:
    """Give a block the box it occupies, and place its lines from that box.

    A word processor's text box IS the layout: the words wrap to its width, sit
    centred in it, and move when it moves. This app had three separate answers
    to "where does line 3 go" - the fitter's, the browser's preview, and the
    box you type into - and they agreed only by luck. What lee saw was the
    words jumping the moment he clicked them, because clicking swapped one
    answer for another.

    So the fitter still decides everything that matters - the size, the breaks,
    which chord of the balloon each line sits in - and then this hands the
    result over as a box plus the one piece of arithmetic every other engine
    already uses to fill a box. Nothing here re-fits and nothing here moves a
    block: the frame is drawn around where the lines already are.
    """
    lines = lay.lines
    if not lines or not lay.line_origins:
        return lay
    if lay.fixed:
        # Already two blocks in one box - a speech divided between the lobes
        # of a double balloon, or an effect running along its own axis. Its
        # lines are NOT evenly spaced down one box and re-deriving them from
        # one is what would drag the second half back up into the waist.
        return lay
    path = lay.font_path or cfg.font_path
    lh = float(lay.font_size) * float(lay.leading or 1.0)
    xs = [x for x, _ in lay.line_origins]
    ys = [y for _, y in lay.line_origins]
    cx = sum(xs) / len(xs)
    cy = (min(ys) + max(ys)) / 2.0
    widest = max(_text_w(path, lay.font_size, ln) for ln in lines)
    fw = max(8, int(round(widest + 2 * PAD_PX)))
    fh = max(8, int(round(len(lines) * lh)))
    fx = int(round(cx - fw / 2.0))
    fy = int(round(cy - fh / 2.0))
    lay.frame = (fx, fy, fw, fh)
    top = fy + (fh - len(lines) * lh) / 2.0
    xi = int(round(cx))
    lay.line_origins = [(xi, int(round(top + (k + 0.5) * lh)))
                        for k in range(len(lines))]
    return lay


def apply_align(lay: "TextLayout", cfg: TypesetConfig, how: str) -> "TextLayout":
    """Hang the lines off the left or right edge of the block instead of its
    middle.

    Everything was centred, which is right for a balloon and wrong for a
    caption: a block of narration ranged left is what a typesetter sets, and
    there was no way to ask for it.

    The renderer draws each line CENTRED on its origin, so aligning is a matter
    of moving each origin by half the difference between that line and the
    widest one - the frame does not move and nothing else has to know.
    """
    if how not in ("left", "right") or not lay.lines or not lay.line_origins:
        return lay
    path = lay.font_path or cfg.font_path
    widths = [_text_w(path, lay.font_size, ln) for ln in lay.lines]
    widest = max(widths) if widths else 0
    out = []
    for (x, y), w in zip(lay.line_origins, widths):
        d = (widest - w) / 2.0
        out.append((int(round(x - d if how == "left" else x + d)), y))
    lay.line_origins = out
    return lay


def _chord_at(m: np.ndarray, ya: float, yb: float) -> tuple[int, int]:
    """Leftmost and rightmost column the shape occupies across rows [ya, yb].

    Every row in the band has to hold the line, so this is the INTERSECTION of
    the rows' spans, not their union - on a curve the narrowest row is the one
    that decides, and taking the union is how a line's corners ended up out
    past the outline.
    """
    ya = int(max(0, np.floor(ya)))
    yb = int(min(m.shape[0], np.ceil(yb) + 1))
    if yb <= ya:
        return (0, -1)
    lo, hi = 0, m.shape[1] - 1
    for row in range(ya, yb):
        xs = np.flatnonzero(m[row])
        if xs.size == 0:
            continue
        lo, hi = max(lo, int(xs[0])), min(hi, int(xs[-1]))
    return (lo, hi)


def _one_character(region) -> bool:
    """Is the Japanese in this box a single character?

    lee: *"also if the jappennese sfx chareter is just one charater in the box
    it shoud just be flat with no angle"*.

    He is right about the geometry, not only the look. `sfx.sfx_frame` fits an
    axis through the ink, and an axis through ONE glyph is not a direction of
    writing at all - it is the long way through that glyph's own shape. ン
    slopes down-left and ク slopes down-right, so two single-character effects
    set side by side come out leaning opposite ways for no reason anybody
    reading the page could see. It takes two characters before there is a line
    between them to measure.

    Whitespace out, and composed first: ド is one character, and a reader that
    hands it back as ト plus a combining ゙ is describing the same one glyph in
    two codepoints. `NFC` puts it back together, so the count is of characters
    rather than of the way they happened to be encoded.
    """
    import unicodedata
    s = "".join((getattr(region, "src_text", "") or "").split())
    return len(unicodedata.normalize("NFC", s)) == 1


def fit_sfx_region(region: TextRegion, text: str,
                   cfg: TypesetConfig) -> Optional[TextLayout]:
    """Lay a sound effect out along the axis the Japanese one was drawn on.

    A sound effect is not dialogue. It has no bubble to sit inside and it
    leans, but it is still one English word set to be read across, however the
    Japanese ran. The shape it has to fill is the shape the original filled,
    measured at detection while the Japanese was still on the page
    (project.measure_sfx); a region nobody measured falls back to the only
    footprint left, its own box.

    Returns None when there is nothing to lay out, so the caller can carry on
    down the ordinary path.
    """
    from .sfx import SfxFrame, fit_sfx

    if not text.strip():
        return None
    x, y, w, h = [int(v) for v in (region.bbox or (0, 0, 0, 0))]
    if w < 4 or h < 4:
        return None

    lf = float(getattr(region, "sfx_len", 0.0) or 0.0)
    wf = float(getattr(region, "sfx_wid", 0.0) or 0.0)
    if lf > 0 and wf > 0:
        vertical = bool(getattr(region, "sfx_vertical", h >= w))
        angle = 0.0 if _one_character(region) \
            else float(getattr(region, "angle", 0.0) or 0.0)
    else:
        # Never measured: detected before the axis reader existed, or drawn by
        # hand since. Typesetting it straight, filling the box, is what the
        # fitter did for it before and is still the honest answer.
        lf = wf = 1.0
        vertical, angle = h >= w, 0.0
    if SFX_FILLS_BOX:
        # lee: *"make it so that teh sfx is teh size of teh box, like make it
        # fie exacly the size of the box"*. The footprint of the JAPANESE ink
        # is a smaller rectangle than the box round it - measured over his 23
        # pages, `sfx_len` averages 0.82 and `sfx_wid` 0.66 - so an effect
        # fitted to the ink filled about five sixths of the space it was given.
        # The ANGLE and the axis are still read from the ink: which way the
        # effect leans is a fact about the drawing, and only the size budget
        # comes from the box.
        lf = wf = 1.0

    # THIS region's face, not the project's default one.
    #
    # It read `cfg.font_path` directly, which quietly ignored the sound-effect
    # font. On a project that set both - lee's set `font` to Anime Ace and
    # `fonts["sfx"]` to Wild Words - the effect was MEASURED and recorded in
    # Anime Ace while the panel said Wild Words, because the layout carries
    # `font_path` and `typeset_page` only fills that in when it is empty.
    # Every other kind goes through `font_for`; this one had been left out of
    # it, and nothing noticed until `font_for` stopped returning `cfg.font_path`
    # for everything and the two answers came apart.
    path = font_for(cfg, getattr(region, "kind", "") or "") or cfg.font_path

    def measure(size: int, s: str) -> tuple:
        top, bot = ink_extents(path, int(size), _has_descenders(s))
        return (_text_w(path, int(size), s), bot - top)

    frame = SfxFrame(x + w / 2.0, y + h / 2.0,
                     float(max(w, h)) * lf, float(max(1, min(w, h))) * wf,
                     angle, vertical, 1.0, 0)
    # The sweep stops at the MINIMUM, not at the absolute floor. An effect
    # that will not fit the space the original filled comes back at the
    # minimum, bigger than that space, and stays that way - it is drawn on
    # artwork, and running past the box beats being too small to read.
    # lee: *"outside text and sfx shoud be able to got outside teh box if the
    # text size is bellow the miimum"*.
    lay = fit_sfx(frame, text, measure, lo=cfg.min_font, hi=160,
                  over_long=1.0 if SFX_FILLS_BOX else None,
                  over_wide=1.0 if SFX_FILLS_BOX else None)

    # The line sits on its own ink, not on a line box: anchored on the line box
    # a word of capitals hangs off the descender line and sits low in the space
    # the original filled, which on an effect with no bubble round it is the
    # difference between replacing the Japanese and floating near it.
    heights, widths, tops = [], [], []
    for line in lay.lines:
        t, b = ink_extents(path, lay.size, _has_descenders(line))
        heights.append(b - t)
        widths.append(_text_w(path, lay.size, line))
        tops.append(t)
    run = sum(heights) + lay.gap * max(0, len(lay.lines) - 1)
    across = max(widths) if widths else 0.0

    origins, cur = [], lay.cy - run / 2.0
    for hh, tt in zip(heights, tops):
        origins.append((int(round(lay.cx)), int(round(cur - tt))))
        cur += hh + lay.gap

    if not lay.fitted:
        region.flagged = ("overflow: this sound effect does not fit the space "
                          "the original filled")
    # `spills` is NOT set here. Whether the words stick out of the BOX is
    # `clamp_to_box`'s question and it is asked two lines after this returns;
    # `lay.fitted` answers a different one - whether they fit the space the
    # original ink filled - and it already sets `fit_ok` and the flag. Setting
    # both from one number made a mutant of the other indistinguishable.
    return TextLayout(
        lines=lay.lines, font_size=lay.size,
        leading=round(run / max(1, len(lay.lines)) / max(1, lay.size), 3),
        line_origins=origins, font_path=path, fit_ok=bool(lay.fitted),
        # sfx.py reports the tilt the way the page reads it - clockwise
        # positive. A layout's `rotate` turns the other way, the way PIL and
        # the browser preview both already turn it.
        rotate=-float(lay.angle),
        frame=(int(round(lay.cx - across / 2.0)), int(round(lay.cy - run / 2.0)),
               max(8, int(round(across))), max(8, int(round(run)))),
    )


# How much bigger the broken layout has to be before the break is worth making.
# The two ends of the range say what it is for: lee's "Double...?!" goes 11 to
# 18 in the balloon it was starved in, and in a balloon with room to spare the
# same break goes 39 to 40 - a word cut in half to tidy the arithmetic by a
# point, which is a break for its own sake and one nobody asked for.
#
# A ratio and not a number of points, because a step of size is a large thing
# at 11pt and a small one at 39. The chapter is nearly flat between a tenth and
# a quarter - mean point size 17.39, 17.34, 17.19 at 1.10, 1.15 and 1.25, with
# the same 39 blocks under a third of their balloon either way - so this is a
# choice about the ONE-POINT case and not about the numbers, and a sixth is far
# enough above it to be sure.
AUTHOR_BREAK_GAIN = 1.15


# ------------------------------------------------ and breaking a word itself

# lee: *"i dont wanta buch of hypers everywhere"*. That is a rate, and the
# published English chapter 22 has one: read off the pages with tesseract,
# **7 of 302 lines end in a broken word - 2.3 per 100**. Everything below is
# in service of landing on that number rather than on whether each break looks
# defensible on its own.
#
# Four separate brakes, because one threshold doing all the work is one number
# nobody can reason about:
HYPHEN_MIN_WORD = 8    # short words are never broken, whatever the patterns say
HYPHEN_MIN_HEAD = 3    # letters kept before the hyphen. The pattern file allows
HYPHEN_MIN_TAIL = 3    # 2; two letters and a dash is a stub, not a syllable.
HYPHEN_MAX = 1         # broken words per block. A professional does one.

# How much bigger the broken layout must be to be worth a hyphen.
#
# lee: *"i dont wanta buch of hypers everywhere"*. So the question is a RATE,
# and four published English chapters were read with tesseract to find it
# (`his/hyph.py`) - deliberately not one, because one chapter is the work of
# one person and would only measure that person's habit:
#
#     Jujutsu Kaisen 22        7 of 302     2.3 per 100
#     chapter 141             12 of 486     2.5
#     My Hero Academia 425     6 of 448     1.3
#     My Hero Academia 420     3 of 360     0.8
#     ----------------------------------------------
#     pooled                  28 of 1596    1.8
#
# They disagree, which is worth more than agreement would have been: a house
# that hyphenates twice as often as another means there is no single right
# answer, only a range, and the honest place to sit is the middle of it.
#
# Swept over lee's 23 pages (`his/rate.py`), counted the same way on both
# sides - two letters and a hyphen ending a line that is not the last of its
# block, em-dashes excluded:
#
#     gain    lines   broken   per 100   mean pt
#     1.00      789      29      3.7      16.69
#     1.10      784      18      2.3      16.65
#     1.25      781      16      2.0      16.60
#     1.30      779      14      1.8      16.55   <-
#     1.35      778      13      1.7      16.53
#     1.40      776      12      1.5      16.46
#     1.60      773      10      1.3      16.36
#
# On the pooled figure exactly. Both numbers include the dashes the AUTHOR
# wrote: with hyphenation off entirely lee's chapter still has 4 such lines
# (0.5 per 100 - "Glow-", "Villainess-"), so of the 14 at this setting, ten
# are ours.
#
# One caveat, recorded because it points the other way: the reading
# UNDERCOUNTS. `COORDI-/NATES` appears twice on page 5 of chapter 420 and
# neither was counted - a whole-page read finds them, the per-balloon read
# does not. So the true professional rate is somewhat above 1.8, and if this
# number is ever revisited, revisit it upward and not down.
HYPHEN_GAIN = 1.30


def hyphen_points(word: str) -> list:
    """Where `word` may be broken - at most one place, nearest the middle.

    One place and not all of them. The fitter is freer with three, and freedom
    here is exactly what produces a page of hyphens: every extra offer is
    another line that CAN end in one. A professional breaks a long word about
    once, near the middle, so that is what is offered.
    """
    core = word.strip(_DASHES + _DOTS + ",!?;:\"'()")
    if len(core) < HYPHEN_MIN_WORD or not core.isalpha():
        return []
    from . import hyphen as _hy
    at = word.find(core)
    got = [p for p in _hy.points(core)
           if p >= HYPHEN_MIN_HEAD and len(core) - p >= HYPHEN_MIN_TAIL]
    if not got:
        return []
    mid = len(core) / 2.0
    return [at + min(got, key=lambda p: (abs(p - mid), p))]


def hyphen_tokens(text: str) -> "tuple[list[str], list[bool]]":
    """`text` as tokens the fitter may break between, and which rejoin.

    The piece before a break carries its hyphen ALREADY - `trans-`, `figured` -
    so the fitter measures the wider thing. Two pieces that end up on one line
    are rejoined with the hyphen taken back out, which makes the drawn line
    narrower than the one that was measured and never wider. That is the same
    argument `_fit_on_author_breaks` makes, and it is the whole reason a fit
    that fitted still fits.
    """
    toks: list[str] = []
    glue: list[bool] = []
    for w in text.split():
        pts = hyphen_points(w)
        if not pts:
            toks.append(w)
            glue.append(False)
            continue
        p = pts[0]
        toks.append(w[:p] + "-")
        glue.append(False)
        toks.append(w[p:])
        glue.append(True)
    return toks, glue


def rejoin_hyphens(lines: list, toks: list, glue: list) -> list:
    """The fitter's lines, with every word it did NOT break made whole again -
    and the hyphen that was measured taken back off."""
    out, at = [], 0
    for ln in lines:
        n = len(ln.split())
        built = ""
        for k in range(at, at + n):
            if k >= len(toks):
                return list(lines)
            if k > at and glue[k]:
                built = built[:-1] + toks[k]      # drop the measured hyphen
            elif k == at:
                built = toks[k]
            else:
                built += " " + toks[k]
        at += n
        out.append(built)
    if at != len(toks):
        return list(lines)
    return out


def _fit_on_hyphens(text: str, mask: np.ndarray, cfg: TypesetConfig
                    ) -> Optional[TextLayout]:
    """Fit again, allowed to break long words where English allows it.

    Returns None when there is nothing long enough to break, when the fitter
    took no break it was offered, or when it took more than `HYPHEN_MAX` of
    them - a balloon with three hyphens in it is the thing lee asked not to
    have, and refusing the whole layout is how that is guaranteed rather than
    hoped for.
    """
    toks, glue = hyphen_tokens(text)
    if not any(glue):
        return None
    lay = _best(" ".join(toks), mask, cfg)
    if lay is None:
        return None
    lines = rejoin_hyphens(list(lay.lines), toks, glue)
    took = sum(1 for l in lines[:-1] if l.endswith("-"))
    if not took or took > HYPHEN_MAX:
        return None
    return replace(lay, lines=lines)


def _fit_on_author_breaks(text: str, mask: np.ndarray, cfg: TypesetConfig
                         ) -> Optional[TextLayout]:
    """Fit again, allowed to break at the dashes and dot runs in the text.

    Only reached when the ordinary fit found nothing at `min_font` or above,
    which is exactly the condition lee named. The pieces are handed to the
    fitter spaced apart so it may break between them, and any pair it chose
    NOT to break is put back together as one word before the lines are placed
    - which makes every line no wider than the fitter measured, never wider,
    so a layout that fitted still fits.

    The origins from the spaced-out fit are kept as they are. Re-placing the
    rejoined lines through `place_lines` was tried and returned exactly the
    same origins on every case that rejoins at all, which is what centring
    predicts: a line is centred, so taking a space out of the middle of it
    moves both ends inward and leaves the centre alone. Measured, the rejoin
    takes 5.88px off a line at 14pt and never adds any.

    Returns None when there is no dash or dot run to break at - the caller
    then falls through to the shrink-and-flag path exactly as before.
    """
    toks, glue = author_break_tokens(text)
    if len(toks) <= len(text.split()):
        return None                     # nothing the author wrote to break at
    lay = _best(" ".join(toks), mask, cfg)
    if lay is None:
        return None
    lines = rejoin_author_breaks(list(lay.lines), toks, glue)
    if lines == list(lay.lines):
        return lay                      # every piece broke; nothing to rejoin
    return replace(lay, lines=lines)


# How many lines a block may be given when the alternative is putting it on
# the artwork. `max_lines` is taste - a nine-line balloon looks wrong and the
# scorer is tuned to avoid one - but taste is not worth typesetting over
# somebody's drawing for, and a tall narrow column is exactly what a typesetter
# reaches for in a tall narrow lobe.
DESPERATE_LINES = 24


def _narrower_fit(text: str, mask: np.ndarray, cfg: TypesetConfig
                  ) -> Optional[TextLayout]:
    """The same search again, allowed more lines than the cap.

    lee, with a double balloon whose small lobe had its typesetting lying across
    the outline: *"if the text is going out of the text bot it shoud make teh
    with smaller if posible"*.

    More lines IS a smaller width - the fitter's line count is what decides
    how wide a line may be, and every count is measured against the balloon's
    own chord at that height. So there is nothing to write here but the search
    that already exists, with the one limit lifted that was stopping it: a lobe
    narrow enough to need eleven lines was refused at nine and the block went
    to `_plain_fit`, which wraps into the bounding RECTANGLE - and the corners
    of a rectangle drawn round a round lobe are outside the lobe. That is the
    overflow, and it is why raising the cap fixes it rather than shrinking the
    type again.

    Only ever reached once the ordinary fit and the author's own breaks have
    both failed, so a chapter that typesets normally never comes near it.

    Running the author's breaks again with the cap lifted was tried here and
    taken out. It reads like the obvious combination - the dash shortens a
    line, the lifted cap pays for the extra line it costs - and it is
    unreachable: the cap only binds when the text has many pieces, and when it
    has many pieces the plain search at 24 lines has already found something.
    A sweep of four hyphenated texts over 60 lobe shapes found no case where
    the pair fits and neither half does. Speculation with no case behind it is
    a line nothing can test.
    """
    if cfg.max_lines >= DESPERATE_LINES:
        return None
    return _best(text, mask, replace(cfg, max_lines=DESPERATE_LINES))


def fit_region(region: TextRegion, cfg: TypesetConfig,
               mask: "Optional[np.ndarray]" = None) -> TextLayout:
    """Lay the translation out, and turn it with the box if the box is turned.

    A box somebody rotated is stored as a tilted rectangle, so `place_mask()`
    is a tilted shape - and fitting into that directly would set the lines
    level inside a leaning box, which is a staircase, not turned text. So the
    fit is done against the box UPRIGHT and the finished block is turned about
    the same centre the box turns about. The renderer already does that for any
    layout carrying `rotate`; see `render.py`.

    lee: *"alow me to rotate boxes ... the box and the text together"*.

    Not a sound effect: those are already laid along an axis of their own,
    letter by letter, and the turn reaches them by moving that axis - see the
    region endpoint. Sending one through here would replace that with a block
    of level lines in a box.
    """
    turn = float(getattr(region, "turn", 0.0) or 0.0)
    if (getattr(region, "manual", False) and abs(turn) > 0.01 and mask is None
            and _kinds.family_of(getattr(region, "kind", "") or "") != "sfx"):
        x, y, w, h = (int(v) for v in region.bbox)
        pm = region.place_mask()
        up = np.zeros(pm.shape[:2] if pm is not None else (y + h, x + w),
                      np.uint8)
        up[max(0, y):y + h, max(0, x):x + w] = 255
        lay = _fit_region(region, cfg, up)
        if lay is not None:
            lay.rotate = turn
        return lay
    # OUTSIDE TEXT IS SET STRAIGHT, and that is a decision rather than an
    # omission.
    #
    # It leaned for one afternoon. The reading gives loose writing an angle
    # now - lee: *"is posible while looking at the box type with reas text ask
    # it to give the angle of the text for the typesetter"* - and this is
    # where a freefloat block was turned by it. He looked at the result and
    # said: *"also make all teh freefloast text be start no more angle"*.
    #
    # So the block goes down level. A sound effect still leans, because it
    # reaches its angle by another road entirely - laid letter by letter along
    # an axis of its own, which is the branch above this one - and because a
    # leaning effect is drawn that way on purpose. Outside text is a caption
    # on the artwork, and a caption that leans is just harder to read.
    #
    # `region.angle` is still measured and still stored. It is not thrown
    # away, because the box panel shows it and a person can still turn a box
    # with the handle; it is simply not something the typesetter acts on.
    return _fit_region(region, cfg, mask)


def _fit_region(region: TextRegion, cfg: TypesetConfig,
                mask: "Optional[np.ndarray]" = None) -> TextLayout:
    """Best-scoring layout of the full translation - line breaks before
    shrinking, shrinking before clamping, never overflowing, and a word is
    never split.

    `mask` overrides the shape to typeset into without touching the region.
    Only `link_masks` passes it, to re-cut a balloon between the halves of a
    split line; the region keeps the geometry it was detected with, because
    that geometry is what gets saved.
    """
    if mask is None:
        mask = region.place_mask()
    if mask is None or not mask.any():
        # NO SHAPE TO FIT INTO IS NOT A REASON TO TYPESET NOTHING.
        #
        # `place_mask()` is None for every region in a REOPENED chapter -
        # `to_dict` drops the masks, so nothing on disk remembers one - and it
        # is empty for a sound effect whose ink the detector never found.
        # Either way the block came back with no lines in it, which on the
        # page is a balloon that lost its dialogue.
        #
        # The box is what the fitter already falls back to when there is no
        # balloon, and it is the one shape every region always has.
        # lee: *"if the typesetter can't find a box it hsoud fall back to
        # using the box"*.
        mask = region.box_mask(None if mask is None else mask.shape[:2])
    if mask is None or region.dst_text is None:
        return TextLayout(lines=[], font_size=cfg.min_font, leading=1.1, fit_ok=False)

    kind_font = font_for(cfg, region.kind,
                         (region.layout_override or {}).get("font") or "")
    scale = KIND_SCALE.get(getattr(region, "kind", ""), 1.0)
    if scale > 1.0:
        # Room to grow, not an instruction to. The fitter still shrinks to the
        # shape, so a burst in a small balloon comes out exactly as it did.
        cfg = replace(cfg, max_font=int(round(cfg.max_font * scale)))
    # the faces to fall back through if the chosen one cannot draw this line
    spares = [f for f in (cfg.font_path, spare_font()) if f]
    if kind_font and kind_font != cfg.font_path:
        cfg = replace(cfg, font_path=kind_font)

    m = mask > 0
    # the text is made drawable by THIS region's font before anything is
    # measured - the export must never show a tofu box
    safe_text = sanitize_for_font(region.dst_text, cfg.font_path,
                                  cfg.substitutes)
    if not keeps_the_words(region.dst_text, safe_text) and cfg.substitutes:
        # The font chosen for this region cannot draw its dialogue: a symbol
        # face, or one with no lowercase. Typeset it in something that can
        # rather than laying out the stub that is left - text in the wrong
        # face is a thing you can see and put right, an empty bubble is not.
        for alt in spares:
            if alt == cfg.font_path:
                continue
            alt_text = sanitize_for_font(region.dst_text, alt)
            if keeps_the_words(region.dst_text, alt_text):
                cfg = replace(cfg, font_path=alt)
                safe_text = alt_text
                region.flagged = ("the chosen font cannot draw this text — "
                                  f"typeset in {os.path.basename(alt)}")
                break
    # ...and with substitutes off, say when the face is short of something.
    # The words are still set in it - this is a remark, not a rescue.
    if not cfg.substitutes and cfg.font_path and region.dst_text:
        missing = [c for c in set(normalize_text(region.dst_text))
                   if c not in "\n\t " and not font_supports(cfg.font_path, c)]
        if missing:
            region.flagged = (
                "%s has no glyph for %s" %
                (os.path.basename(cfg.font_path),
                 " ".join(sorted(missing))[:60]))
    text = safe_text.upper() if cfg.uppercase else safe_text
    if not text.strip():
        # No face here can draw a word of it. Say so; an empty layout leaves
        # whatever was typeset before in place (see typeset_page) instead of
        # replacing it with a blank line nobody can see.
        region.flagged = "no available font can draw this text"
        return TextLayout(lines=[], font_size=cfg.min_font, leading=1.1,
                          fit_ok=False)

    if _kinds.family_of(region.kind) == "sfx":
        # A sound effect answers to its own shape, not to a bubble's chords -
        # but it still has to stay in its box, or near enough. See clamp_to_box.
        lay = fit_sfx_region(region, text, cfg)
        if lay is not None:
            return clamp_to_box(region, lay, cfg)

    # The full translation goes in, always - line breaks and size do the
    # fitting, and a word is never split.
    lay = _best(text, m, cfg)
    # A balloon with a waist in it typesets as two lobes if that typesets bigger.
    two = _two_lobe_fit(region, text, m, cfg, lay)
    if two is not None:
        return two

    # ...and the dashes and dot runs the author already wrote are tried the
    # same way, and kept on the same condition: only if they typeset BIGGER.
    #
    # They used to be a last resort, reached only when nothing fitted at the
    # minimum at all. That is one of the two cases they are for and it is not
    # the common one. The other is a single long word in a tall narrow balloon,
    # where the width of that one word is the whole ceiling: "Double...?!" is
    # 77px at 11pt against a widest usable chord of 84, so eleven - the floor -
    # was the largest size that fitted, in a balloon 102 wide and 214 tall with
    # nothing else in it. Broken where the author put the dots it sets at 18
    # on two lines. Nothing was wrong with the fitter's arithmetic; it was
    # never allowed to consider the layout.
    #
    # BIGGER and not better-scoring, deliberately. The two fits are scored
    # against different `_feasible_top`s - `small` is normalised by what THAT
    # arrangement can reach - so their scores are not on one scale, while their
    # point sizes are. It is also the thing lee is asking about: *"try to make
    # teh typesetting more constsant and better fit the boxes"*.
    alt = _fit_on_author_breaks(text, m, cfg)
    if alt is not None and (lay is None
                            or alt.font_size >= AUTHOR_BREAK_GAIN * lay.font_size):
        return alt
    # ...and only then a hyphen of our own. AFTER the author's dashes, because
    # a break the text already carries is free and one we invent is a mark that
    # was not there - so if both would do, the author's wins.
    #
    # Measured against the best of BOTH, not against the plain fit. Against the
    # plain fit alone there is a hole: an author break that just missed its own
    # gain gets discarded, and the hyphen is then compared with a layout nobody
    # was going to use - so it wins on a margin it never had. That sets
    # `YOU'RE / BLEED- / ING...` over lee's own `YOU'RE / BLEEDING / ...`, and
    # his four hand-set examples are in the suite exactly so that this cannot
    # happen quietly.
    floor = lay
    if alt is not None and (floor is None or alt.font_size > floor.font_size):
        floor = alt
    cut = _fit_on_hyphens(text, m, cfg)
    if cut is not None and (floor is None
                            or cut.font_size >= HYPHEN_GAIN * floor.font_size):
        return cut
    if lay is not None:
        return lay
    if alt is not None:
        return alt
    if cut is not None:
        return cut

    # Outside text has no balloon to stay inside - the only thing under it is
    # the drawing. Rather than dropping under the minimum size to stay in a
    # box that was never the right shape for English, set it AT the minimum
    # and let it run out onto the artwork. lee: *"outside text and sfx shoud
    # be able to got outside teh box if the text size is bellow the miimum"*.
    #
    # BEFORE the narrower fit below, and that order is the whole point. The
    # box round free text is where the JAPANESE ink was, and Japanese runs
    # down the page in a narrow column - so there is nearly always a way to
    # cram English into it by stacking one word per line, and the narrower fit
    # will find it. That is not typesetting, it is a tower. What lee asked for on
    # this kind of box is the opposite: leave it, at a size somebody can read.
    if _kinds.family_of(region.kind) == "freefloat":
        lay = _spill_fit(text, m, cfg)
        if lay is not None:
            return lay

    # SPEECH, still homeless. A balloon IS a wall, so before dropping under
    # the legibility floor to stay inside one, let the block be narrower -
    # more lines, shorter ones - than the line cap normally permits.
    # lee: *"if the text is going out of the text box it shoud make teh with
    # smaller if posible"*.
    lay = _narrower_fit(text, m, cfg)
    if lay is not None:
        return lay

    # Nothing fit above the legibility floor. Fall back to a plain rectangular
    # wrap, shrinking to the absolute floor, and flag it for a human.
    lay = _plain_fit(text, m, cfg)
    if lay is not None:
        # Only say it shrank if it shrank. This path used to flag every layout
        # it returned, including the ones that came back AT the minimum - and
        # now that it breaks at the author's dashes it reaches the minimum far
        # more often. A red bar on a page that is perfectly well typeset
        # teaches people to stop reading the red bars.
        if lay.font_size < cfg.min_font:
            region.flagged = ("overflow: shrunk below the minimum font size "
                              f"({lay.font_size}pt) to fit the box")
        return lay

    # Even the floor will not fit. Emit one clamped line so nothing lands on
    # the artwork, and flag it loudly.
    text = safe_text
    bx, by, bw, bh = _box_of(m)
    region.flagged = "overflow: text cannot fit this box at any legible size"
    return TextLayout(
        lines=[text], font_size=cfg.absolute_floor, leading=1.0,
        line_origins=[(int(bx + bw / 2), int(by + bh / 2))],
        font_path=cfg.font_path, fit_ok=False,
    )


# How thick an outline is when nobody has chosen one.
#
# Typesetting that sits out on the artwork - sound effects, and the free-floating
# lines that belong to no balloon - has no white paper behind it, so the edge
# is the only thing keeping it legible against tone and detail; a single pixel
# reads as a smudge at page size. Typesetting inside a balloon has the balloon
# doing that job and wants no more than a hairline.
OUTLINE_ON_ART = 2
OUTLINE_IN_BUBBLE = 1

# WHERE A RIM STOPS GROWING WITH THE TYPE IT GOES ROUND.
#
# lee: *"the outlint to text ratio is too nig make it so that taxt over a
# certain size get a samller ratio"* - and then, on which blocks: *"that shoud
# only apply for the other sfx"*, *"ot the big ones"*.
#
# `font_size // 7` is not merely too thick, it is the wrong SHAPE, and his own
# chapter says so. Every keyline `inkstyle` measured off the writing the
# artist drew by hand, by point size:
#
#     144 -> 4    57 -> 4    36 -> 3    19 -> 3    14 -> 4
#     134 -> 4    55 -> 4    20 -> 3    18 -> 4    13 -> 3
#                 48 -> 4               17 -> 4    12 -> 3
#                 46 -> 4
#
# Three or four pixels from 12pt to 144pt. A twelvefold range of type and one
# nib, which is the rule `_measured_width` already states - *a pen has a
# width* - and which had never reached the automatic path. At 144pt the old
# rule asks for twenty where the artist drew four.
#
# So: the drawing rate up to the knee, and a crawl past it. The knee is where
# `size // 7` and the measurement agree, which is why it is 28 rather than a
# round number.
#
#     28 -> 4    46 -> 4    55 -> 5    72 -> 5    144 -> 7
#
# It stays a ratio rather than becoming the flat 4 the numbers alone would
# suggest, because a rim is in PAGE pixels: lee's scans are 960 wide, and the
# same page at 2000 would want a proportionally thicker line. A constant would
# come out as a hairline there.
#
# EVERY sound effect, the big ones included. It was every one EXCEPT the big
# ones - lee: *"ot the big ones"* - and he asked for that exemption back after
# looking at the result: *"the big sfx shoud also use rim now"*.
#
# He is right, and the reasoning it replaces was thinner than it sounded. A big
# sound is where `size // 7` is at its very worst, precisely because it is a
# ratio: the block with the largest type gets the heaviest keyline, and 144pt
# asks for twenty pixels where the artist of this chapter drew four. "An impact
# effect is the one place a heavy rim is the drama rather than a mistake" was a
# defence of the single case the measurement most flatly contradicts.
#
# A block that WAS measured keeps its measured rim regardless of any of this:
# `_measured_width` runs after, and these constants are the answer for pages
# nobody has read.
RIM_KNEE = 28
RIM_SLOW = 40


# How far past its own box a sound effect may reach, per side, as a fraction of
# that side.
#
# It was 0.25 - lee, in July: *"outide text and sfx should try to fit inside
# the box or slightly bigger"*. "Slightly bigger" is now nothing: *"make it so
# that teh sfx is teh size of teh box, like make it fie exacly the size of the
# box, it shou only ever outside teh box if tehsfx would break teh minimun size
# for teh text"*. The second half of that sentence is the escape hatch below,
# which was already here and is what keeps this from being a wall: an effect
# that cannot fit at `min_font` stays too big and sets `spills`.
SFX_MARGIN = 0.0

# ...and the size is grown against the BOX rather than against the footprint of
# the Japanese ink inside it. See `fit_sfx_region`.
SFX_FILLS_BOX = True


def clamp_to_box(region: TextRegion, lay: TextLayout, cfg: TypesetConfig,
                 margin: float = SFX_MARGIN) -> TextLayout:
    """Keep a sound effect inside its own box, or a little past it.

    A sound effect is laid out along the axis the JAPANESE ran on, and Japanese
    effects run down the page. The English runs across, so a tall narrow box
    got a wide short line: CRASH!! in a 120x260 box came out 237 wide and hung
    59px out of each side, over the artwork.

    `enforce_bounds` is no good here - it clamps line by line into a mask and
    would straighten a leaning effect back up, which is exactly what an effect
    must not do. This only makes the letters SMALLER, keeps the angle, and
    keeps the effect centred where it was.
    """
    if not lay.lines or not lay.line_origins:
        return lay
    x, y, w, h = [int(v) for v in (region.bbox or (0, 0, 0, 0))]
    if w < 4 or h < 4:
        return lay
    path = lay.font_path or cfg.font_path
    # Measured on the INK, the way `fit_sfx_region` measures it - not on the
    # font's ascent-plus-descent.
    #
    # The two disagreed, and `SFX_MARGIN` used to hide it: the fit asked
    # whether the letters fit and the clamp asked whether the LINE BOX did,
    # which on a word of capitals includes room for a descender that is not
    # there. At a quarter of slack per side nobody noticed. At nothing - lee's
    # *"exacly the size of the box"* - the clamp shaved a few points off every
    # effect the fit had just declared a fit, and `KA` in a 60x60 box came out
    # of the fitter at 63pt and out of the clamp at 58.
    #
    # Ink is also the honest measure of the question being asked. What has to
    # sit inside the box is what a reader can see, and an effect held back to
    # leave room for the descender of a word that has none is an effect
    # smaller than the box it was asked to fill.
    heights, widths = [], []
    for line in lay.lines:
        top, bot = ink_extents(path, lay.font_size, _has_descenders(line))
        heights.append(bot - top)
        widths.append(_text_w(path, lay.font_size, line))
    gap = max(0.0, (float(lay.leading or 1.0) - 1.0) * lay.font_size)
    th = sum(heights) + gap * max(0, len(lay.lines) - 1)
    tw = max(widths)
    # A leaning effect covers the box of its own rotated rectangle.
    a = math.radians(float(lay.rotate or 0.0))
    ca, sa = abs(math.cos(a)), abs(math.sin(a))
    ext_w, ext_h = tw * ca + th * sa, tw * sa + th * ca
    room_w, room_h = w * (1 + 2 * margin), h * (1 + 2 * margin)
    scale = min(room_w / max(1.0, ext_w), room_h / max(1.0, ext_h))
    if scale >= 1.0:
        return lay          # it already fits: the clamp only ever shrinks
    # ...and it never shrinks past the minimum. A sound effect is drawn ON the
    # artwork, so the box round it is a note of where the Japanese ink was and
    # not a wall: given the choice between an effect that runs past its box and
    # one too small to read, the typesetter takes the first every time. lee:
    # *"outside text and sfx shoud be able to got outside teh box if the text
    # size is bellow the miimum"*.
    #
    # An effect the fitter already set below the minimum is not GROWN here -
    # the guard three lines down does that, and it is the only thing that
    # needs to: this function only ever shrinks.
    floor = cfg.min_font
    want = int(lay.font_size * scale)
    size = max(floor, want)
    if want < floor:
        lay.spills = True   # stopped by the floor: it stays past its box
    if size >= lay.font_size:
        return lay
    # Shrink about the effect's OWN centre, so it stays over the thing it was
    # drawn on. Shrinking about the middle of the box would slide it: a sound
    # effect is placed where the Japanese ink was, which is not the middle of
    # the rectangle drawn round it.
    cx = sum(px for px, _ in lay.line_origins) / len(lay.line_origins)
    cy = sum(py for _, py in lay.line_origins) / len(lay.line_origins)
    k = size / float(lay.font_size)
    lay.line_origins = [(int(round(cx + (px - cx) * k)),
                         int(round(cy + (py - cy) * k)))
                        for px, py in lay.line_origins]
    lay.font_size = size
    # ...and the frame with them. This was missing, and a frame is not
    # decoration: it is what the editor draws the selection with, what a drag
    # moves, what `frameOf` hands the browser to place lines from, and what a
    # save writes into `layout_override`. Left at the pre-shrink size it says
    # the block is as big as it was BEFORE the clamp - `Um...` on lee's page 5
    # measured 41x20 on the paper and carried a frame claiming 94x40.
    #
    # The SAME similarity transform the origins just went through, rather than
    # a fresh measurement. Re-measuring was tried and it drifts: `cx, cy` above
    # is the mean of the ORIGINS, which sit on each line's ink top and are not
    # the block's visual centre, so a frame rebuilt around that point lands a
    # few pixels off the one `fit_sfx_region` built - 3.5px on the leaning
    # effect in `test_a_sound_effect_is_typeset_along_the_axis_it_was_drawn_on`,
    # which is a test about an effect staying centred on its box and was right
    # to complain. Scaling the frame the way the letters were scaled keeps it
    # in exactly the relationship to them it had before the clamp, which is the
    # only thing this function is entitled to change.
    if lay.frame and len(lay.frame) == 4:
        fx, fy, fw, fh = lay.frame
        lay.frame = (int(round(cx + (fx - cx) * k)),
                     int(round(cy + (fy - cy) * k)),
                     max(8, int(round(fw * k))), max(8, int(round(fh * k))))
    return lay


def on_art(region) -> bool:
    """Is there artwork behind this text rather than a balloon?

    Kind is a label a person can set and often has not: lee's on-art narration
    came through as `narration`, which is a perfectly good description of what
    it says and no description at all of what is behind it, so it was typeset
    with the hairline outline that belongs to speech on paper and disappeared
    into the drawing. What actually decides the question is whether a balloon
    was ever found round the words. A region with no balloon mask has nothing
    but artwork behind it, whatever it is called.

    Asked by FAMILY, not by the literal kind. The three kinds a box starts
    with are the family names, but a sub-type is its own string - `caption`,
    `whisper`, `impact` - so `kind in ("freefloat", "sfx")` was false for every
    box a person had actually typed, and outside text and sound effects fell
    through to the balloon test below.

    Which they then failed, for a second reason: a block with no balloon is
    given a placement RECTANGLE by `give_room`, and that rectangle is stored
    in `bubble_mask`. So "was a balloon ever found round the words" was
    answered yes for a block standing on bare artwork, and it was typeset
    with the hairline outline that belongs to speech on paper.
    lee: *"the default outile for outisde text and sfx shoud be 2 for the
    typessetter"*.
    """
    if _kinds.family_of(getattr(region, "kind", "")) in ("freefloat", "sfx"):
        return True
    return getattr(region, "bubble_mask", None) is None


def default_stroke(region) -> int:
    """The outline width for a region nobody has set one on."""
    return OUTLINE_ON_ART if on_art(region) else OUTLINE_IN_BUBBLE


ON_PAGE_PX = 24        # how much of a block must stay reachable


def _frame_on_page(frame, shape) -> tuple:
    """A block's box, dragged back until part of it is on the paper again.

    A frame is free to hang over the edge - that is how a sound effect runs
    off the side of a panel. What it may not do is leave altogether: a block
    whose whole box is past the edge is not drawn, not clickable and not
    reachable by any means, so the only thing left to do with it is delete the
    box and start again. lee: *"the etxt box shifted out of the page and is
    now stuck and unclicable"*.

    `ON_PAGE_PX` of it is kept on, in whichever direction it went.
    """
    H, W = int(shape[0]), int(shape[1])
    x, y, w, h = (int(v) for v in frame)
    keep = ON_PAGE_PX
    x = max(min(x, W - keep), keep - w)
    y = max(min(y, H - keep), keep - h)
    return (x, y, w, h)


def _empty_layout(region, cfg, ov) -> "TextLayout":
    """A text block with nothing in it - kept, not thrown away.

    Emptying a box is an edit like any other, and the box has to survive it:
    at the size it was, where it was, so it can be clicked and typed into
    again or deleted. lee: *"if i dlete all teh text from a text box its shoud
    accesp the edit and stay the last size it was and i shoud be able to lcick
    on it to add text or dleete it"*.

    It keeps its FRAME, which is what everything downstream uses to know where
    the block is - the editor draws a placeholder there, and the exporter
    draws nothing at all, which is right: an empty block is empty.
    """
    size = int(ov.get("font_size") or cfg.min_font)
    size = max(cfg.absolute_floor, min(size, 200))
    frame = [int(v) for v in (ov.get("frame") or [])]
    if len(frame) != 4:
        x, y, w, h = (int(v) for v in region.bbox)
        frame = [x, y, max(1, w), max(1, h)]
    m = region.place_mask()
    if m is not None:
        frame = list(_frame_on_page(frame, m.shape))
    return TextLayout(
        lines=[], font_size=size,
        leading=float(ov.get("leading") or MIN_LEADING),
        line_origins=[], score=0.0,
        font_path=font_for(cfg, region.kind, ov.get("font") or ""),
        fit_ok=True, frame=frame)


def empty_layout_for(region, cfg: TypesetConfig | None = None,
                     was: dict | None = None) -> "TextLayout":
    """The layout for a block whose words have been deleted.

    Deleting the text is an edit, and an edit has to take. `typeset_page` skips
    a block with nothing to set - there is nothing to fit - so the typesetting
    from the run before it stayed on the page and the deletion looked like it
    had been refused. lee: *"the etxt box still rejexcts me deleteing all teh
    text"*. Whoever knows a block HAD typesetting calls this instead of leaving
    it alone.

    `was` is the layout it is losing, and what it leaves behind is that block's
    own frame and size - lee: *"stay the last size it was"*. Falling back to
    the region's box instead put an emptied balloon back at box size and
    12pt, so the box you clicked afterwards was not the box you had emptied.
    """
    cfg = cfg or TypesetConfig()
    if not cfg.font_path:
        cfg.font_path = default_font_path()
    ov = dict(region.layout_override or {})
    for key in ("frame", "font_size", "leading", "font"):
        if was and was.get(key) and not ov.get(key):
            ov[key] = was[key]
    return _empty_layout(region, cfg, ov)


def layout_from_override(region: TextRegion, cfg: TypesetConfig,
                         mask: "Optional[np.ndarray]" = None
                         ) -> Optional[TextLayout]:
    """Rebuild a layout from a human's edits rather than fitting afresh.

    `mask` is the shape to typeset into, and it must be the SAME shape the fit
    used - for half of a split balloon that is the re-cut half, not the whole
    balloon. Rebuilding against the whole balloon is what sent both halves of
    a shared bubble to the same centre and laid them over each other.
    """
    ov = region.layout_override or {}
    raw = list(ov.get("lines") or [])
    # Every line as it was typed - blank ones and leading spaces included.
    # They used to be stripped and dropped, so a blank line between two
    # paragraphs could not be typed at all and an indent was thrown away.
    # lee: *"allow the text bx to acces line breaks without text and empty
    # space just like photoshop"*.
    lines = [str(l) for l in raw]
    if "lines" in ov and not any(l.strip() for l in lines):
        # Emptied on purpose. The box stays, at the size it was, with nothing
        # in it - a text layer you can click and type into again, or delete.
        # lee: *"if i dlete all teh text from a text box its shoud accesp the
        # edit and stay the last size it was"*. Returning None here is what
        # made an empty box snap back to whatever the fitter last produced.
        return _empty_layout(region, cfg, ov)
    if not lines:
        return None
    if mask is None:
        mask = region.place_mask()
    if mask is None:
        return None
    m = mask > 0
    size = int(ov.get("font_size") or cfg.min_font)
    size = max(cfg.absolute_floor, min(size, 200))
    path = font_for(cfg, region.kind, ov.get("font") or "")
    # Hand-edited lines go through the same glyph guarantee as fitted text -
    # but a line that sanitises to nothing is kept as a blank rather than
    # dropped, because a blank line is a thing somebody typed on purpose.
    if ov.get("caps"):
        lines = [l.upper() for l in lines]
    # `sanitize_for_font` collapses runs of spaces and strips the ends, which
    # is right for a machine translation and wrong for something a person
    # typed: an indent is a decision. Keep whatever was typed at the front of
    # the line and sanitise only what follows it.
    lines = [l[:len(l) - len(l.lstrip(" \t"))]
             + sanitize_for_font(l, path, cfg.substitutes)
             for l in lines]
    while lines and not lines[-1].strip():
        lines.pop()                      # ...except trailing ones, which are
    if not lines:                        # just where the cursor was left
        return _empty_layout(region, cfg, ov)
    # A number typed into the panel is a decision and stands, however tight.
    # lee: *"the line spacing shoud only be a minimun of 1.20 for the
    # typesetting the user shoud be able to go lowwer"*. The floor is on what
    # the FITTER may choose, not on what a person may ask for.
    leading = float(ov.get("leading") or MIN_LEADING)
    lspace = float(ov.get("lspace") or 0.0)   # px between letters
    dx, dy = int(ov.get("dx") or 0), int(ov.get("dy") or 0)

    # The text sits in a frame of its own. It starts life matching the region,
    # but once moved, resized or rotated it is independent: lines are centred
    # in the frame and may extend past the bubble.
    fr = ov.get("frame")
    if fr and len(fr) == 4:
        frame = (int(fr[0]), int(fr[1]), max(8, int(fr[2])), max(8, int(fr[3])))
        frame = _frame_on_page(frame, mask.shape)
    else:
        ys, xs = np.nonzero(m)
        if xs.size == 0:
            return None
        frame = (int(xs.min()), int(ys.min()),
                 int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))

    fx, fy, fw, fh = frame

    # Resizing the box scales the text with it: find the biggest size whose
    # wrapped words still fit the frame. Growing the box grows the text,
    # shrinking it shrinks the text - like any drawing program.
    if ov.get("fit"):
        text = " ".join(lines)
        avail_w = max(8, fw - 2 * PAD_PX)
        avail_h = max(8, fh - 2 * PAD_PX)
        best = None
        lo, hi = cfg.absolute_floor, 200
        while lo <= hi:
            mid = (lo + hi) // 2
            f = _font(path, mid)
            meas = (lambda t, _f=f:
                    _f.getlength(t) + lspace * max(0, len(t) - 1))
            wrapped = wrap_to_width(text, meas, meas(" "), avail_w)
            ok = (bool(wrapped)
                  and len(wrapped) * mid * leading <= avail_h
                  and max(meas(l) for l in wrapped) <= avail_w)
            if ok:
                best = (mid, wrapped)
                lo = mid + 1
            else:
                hi = mid - 1
        if best:
            size, lines = best
        else:
            # The box is too small even for the floor size; wrap at the floor
            # and let it overflow vertically rather than vanish.
            size = cfg.absolute_floor
            f = _font(path, size)
            wrapped = wrap_to_width(text, f.getlength, f.getlength(" "),
                                    avail_w)
            if wrapped:
                lines = wrapped
    # Resizing the box reflows the words at the same size. Explicit breaks the
    # person typed are kept until the box is resized, at which point the text
    # is re-wrapped to whatever width it now has.
    elif ov.get("wrap"):
        f = _font(path, size)
        measure = lambda t: f.getlength(t) + lspace * max(0, len(t) - 1)  # noqa: E731
        space_w = measure(" ")
        wrapped = wrap_to_width(" ".join(lines), measure, space_w,
                                max(8, fw - 2 * PAD_PX))
        if wrapped:
            lines = wrapped
        if ov.get("snug"):
            # Width was dragged, so the height follows the text: fewer lines
            # in a wider box makes a shorter box, just like a word processor.
            fh = int(round(len(lines) * size * leading + 2 * PAD_PX))

    line_h = size * leading

    # A block nobody has moved is placed the way the fitter places it: each
    # line centred on the balloon's own chord at that height. Centring in the
    # bounding rectangle instead is what made typesetting jump the moment it was
    # clicked - selecting a block wrote an override, and the override put the
    # very same words somewhere else. Only once the block has actually been
    # dragged, turned or resized does it become a free-standing frame centred
    # on its own rectangle, which is what a person moving it expects.
    hand_placed = bool(fr) or dx or dy or float(ov.get("rotate") or 0.0) \
        or ov.get("fit") or ov.get("wrap")
    origins = None
    # A speech divided between the two lobes of a double balloon carries its
    # own line positions, because there is no single box whose even spacing
    # would reproduce them. Selecting or dragging such a block must not
    # re-derive them - that is the jump lee filmed, in its last hiding place.
    keep = ov.get("origins") if ov.get("fixed") else None
    kept = bool(keep and len(keep) == len(lines)
                and not ov.get("fit") and not ov.get("wrap"))
    if kept:
        origins = [(int(a) + dx, int(b) + dy) for a, b in keep]
    elif not hand_placed:
        origins = place_lines(lines, m, cfg, size, leading, path)
    if origins is None:
        top = fy + (fh - len(lines) * line_h) / 2.0
        cx = fx + fw / 2.0
        origins = []
        for k in range(len(lines)):
            yc = top + (k + 0.5) * line_h
            origins.append((int(round(cx)) + dx, int(round(yc)) + dy))

    frame = (fx + dx, fy + dy, fw, fh)

    lay = TextLayout(lines=lines, font_size=size, leading=leading,
                     line_origins=origins, font_path=path,
                     rotate=float(ov.get("rotate") or 0.0),
                     frame=frame,
                     stroke=(int(ov["stroke"]) if ov.get("stroke") not in
                             (None, "") else default_stroke(region)),
                     fit_ok=True, score=0.0, fixed=kept)
    # Not moved by hand, so the box is drawn round where the fitter put the
    # words - rather than round the bubble, which is a different rectangle and
    # was the other half of the jump.
    if not hand_placed and _kinds.family_of(region.kind) != "sfx":
        lay = anchor_to_frame(lay, cfg)
    return lay


# What an override says about WHERE the words go, HOW they break and HOW BIG
# they are - the fitter's own job. Everything else in an override (the face,
# the colours, the outline, the shadow, the letter-spacing) is how the
# typesetting is DRESSED, which is a choice about the page rather than a
# correction to the fit, and none of it is thrown away by a re-run.
FITTING_KEYS = ("lines", "font_size", "leading", "dx", "dy", "frame",
                "rotate", "wrap", "snug", "fit", "locked")


def clear_fitting(region) -> None:
    """Forget how this region's typesetting was placed; keep how it was dressed.

    Pressing Typeset means "lay this page out again". A region that was hand
    corrected carries `locked` in its override, and a locked region skips the
    fitter entirely - so on any page that had been touched, Typeset appeared
    to do nothing at all. Dropping the placement keys puts the region back in
    the fitter's hands while the font and colours chosen for it survive.
    """
    ov = region.layout_override
    if not ov:
        return
    left = {k: v for k, v in ov.items() if k not in FITTING_KEYS}
    region.layout_override = left or None


def _stacked_share(regions: list) -> dict:
    """Re-cut one balloon between the stacked halves of a split line.

    A sentence that runs across two blocks inside a single balloon is detected
    as two regions with the same `link`, and the balloon is divided between
    them where the JAPANESE stopped and started. That is the right cut for
    finding them and the wrong one for typesetting them, because the English is
    not the same length as the Japanese it replaces and it does not break in
    the same places. lee's "MY HARD WORK PAID OFF TOO- / -SO TAKE CARE NOW!"
    is the case: the twenty-six-character half was given the narrow top of the
    balloon and the eighteen-character half the wide middle, so one came out
    at 14pt with no room to grow and the other at 18pt with a third of its
    paper empty.

    So divide the balloon's AREA in proportion to how much there is to typeset.
    Equal area per character is equal type size, which is what a typesetter sets
    out to do - both halves in one voice, as big as the balloon will carry.
    """
    masks = _same_shape_masks(regions)
    if masks is None:
        return {}
    texts = [(r.dst_text or "").strip() for r in regions]
    if not all(texts):
        return {}
    boxes = [_box_of(m > 0) for m in masks]
    order = sorted(range(len(regions)), key=lambda i: boxes[i][1])
    regions = [regions[i] for i in order]
    masks = [masks[i] for i in order]
    texts = [texts[i] for i in order]
    boxes = [boxes[i] for i in order]

    # Only blocks stacked one above another inside one balloon. Two regions
    # side by side are not this shape, and two regions in balloons that merely
    # got linked are not one balloon to divide.
    for (ax, ay, aw, ah), (bx, by, bw, bh) in zip(boxes, boxes[1:]):
        overlap = min(ax + aw, bx + bw) - max(ax, bx)
        if overlap < 0.5 * min(aw, bw):
            return {}
        gap = by - (ay + ah)
        if not (-2 <= gap <= 16):
            return {}

    return _row_proportional_cut(regions, masks, texts)


def _same_shape_masks(regions: list):
    """The regions' placement areas, or None if they are not comparable."""
    masks = [r.place_mask() for r in regions]
    if any(m is None for m in masks):
        return None
    if any(m.shape[:2] != masks[0].shape[:2] for m in masks):
        return None
    return masks


def _claim_the_same_paper(masks: list) -> bool:
    """Do two of these placement areas own the same part of the balloon?

    Normally they cannot. `detect.balloon` divides a balloon between the blocks
    inside it and takes a hairline off each share, so the shares are disjoint
    and "no division adopted here" safely means "the detector's own division
    stands". But a balloon can reach the fitter with every block owning ALL of
    it: the second pass finds one balloon for both, a box drawn or tightened by
    hand names the whole thing, and on the way back in every region rebuilds
    its outline from its OWN stored polygon, which is why lee sees a balloon
    change after he has set it. Two blocks owning one balloon both centre
    themselves in it and are drawn one on top of the other - his SO PLEASE,
    EVERYONE, KEEP TO YOUR PLACE IN LINE with the -OKAY? printed through it.

    A tenth of the smaller area is far more than the hairline a real pair of
    shares leaves and far less than a second claim on the same balloon, so
    nothing that used to divide cleanly is dragged into this.
    """
    for i, a in enumerate(masks):
        pa = a > 0
        sa = float(pa.sum())
        for b in masks[i + 1:]:
            pb = b > 0
            sb = float(pb.sum())
            if not sa or not sb:
                continue
            if float((pa & pb).sum()) > 0.10 * min(sa, sb):
                return True
    return False


def _nearest_ink_cut(regions: list, masks: list) -> dict:
    """Divide one balloon by asking every pixel which block it is nearest.

    A last resort, for a balloon whose blocks all claim the whole of it and
    which no band would divide - the balloon is too thin to give a band away,
    or one block has too few letters to be worth one. "Whose pixel is this" is
    a question the Japanese can always answer, so each block keeps the run of
    paper around its own writing and the two are never printed through each
    other. A band cut is the better answer whenever there is one, which is why
    nothing reaches this until every band has been tried and refused.
    """
    u = np.zeros(masks[0].shape[:2], dtype=np.uint8)
    for m in masks:
        u = np.maximum(u, (m > 0).astype(np.uint8))
    away = []
    for r in regions:
        ink = getattr(r, "text_mask", None)
        seed = np.zeros(u.shape, np.uint8)
        if ink is not None and ink.shape[:2] == u.shape and int((ink > 0).sum()):
            seed[ink > 0] = 1
        else:
            x, y, w, h = (int(v) for v in r.bbox)
            seed[max(0, y):y + max(1, h), max(0, x):x + max(1, w)] = 1
        if not int(seed.sum()):
            return {}
        away.append(cv2.distanceTransform((1 - seed).astype(np.uint8),
                                          cv2.DIST_L2, 3))
    pick = np.argmin(np.stack(away), axis=0)
    out: dict = {}
    for i, r in enumerate(regions):
        piece = ((pick == i) & (u > 0)).astype(np.uint8) * 255
        if int((piece > 0).sum()) < 200:
            return {}
        out[r.id] = piece
    return out


# How far a block's typesetting may stray outside its own box, as a fraction of
# that box's short side. lee: *"for buble text make it so that teh text goes
# where teh box is with a little leeway"*.
#
# This is a DECISION, not a measurement, and it overrides an older one. The
# code used to divide a shared balloon into bands and give each block the
# balloon's full width, because English sets in horizontal lines and a block
# squeezed into the narrow column the Japanese stood in letters tiny. That is
# still true - and it is why one block's words ran clear across the other
# block's box, which is the thing lee has now asked twice to never happen.
#
# Both cannot hold. Full width means crossing the other box; staying in your
# own box means less width. lee chose the box. This is the leeway that keeps
# the choice from being brutal: a block may grow a third of its own short side
# in every direction, and no further, and never into anybody else's box.
BOX_LEEWAY = 0.34


def _box_confined(regions: list, masks: list) -> dict:
    """Each block letters where ITS box is, plus a little, and nowhere else.

    The share is the balloon, cut three ways:

    * within `BOX_LEEWAY` of this block's own box, so the words stay where the
      Japanese they replace stood;
    * nearer this block's box than anybody else's, so the leeway of two
      neighbours can never meet in the middle;
    * one piece, because a paragraph goes in one place.

    Only for a balloon with more than one block in it. A block alone in a
    balloon still gets the whole balloon - there is nobody to run into, the
    box and the balloon are the same speech, and typesetting it into the balloon
    is what makes it big and centred.
    """
    if len(regions) < 2:
        return {}
    u = np.zeros(masks[0].shape[:2], dtype=np.uint8)
    for m in masks:
        u = np.maximum(u, (m > 0).astype(np.uint8))
    if not u.any():
        return {}
    away, reach = [], []
    for r in regions:
        x, y, w, h = (int(v) for v in r.bbox)
        x0, y0 = max(0, x), max(0, y)
        x1 = min(u.shape[1], x + max(1, w))
        y1 = min(u.shape[0], y + max(1, h))
        if x1 <= x0 or y1 <= y0:
            return {}
        seed = np.ones(u.shape[:2], np.uint8)
        seed[y0:y1, x0:x1] = 0
        d = cv2.distanceTransform(seed, cv2.DIST_L2, 3)
        away.append(d)
        reach.append(BOX_LEEWAY * max(4.0, float(min(x1 - x0, y1 - y0))))
    own = np.argmin(np.stack(away), axis=0)

    out = {}
    for k, r in enumerate(regions):
        share = ((own == k) & (u > 0)
                 & (away[k] <= reach[k])).astype(np.uint8)
        if not share.any():
            return {}
        n, lab, stats, _ = cv2.connectedComponentsWithStats(share, 8)
        if n > 1:
            big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            share = (lab == big).astype(np.uint8)
        # A share that does not even cover the box it belongs to is not a
        # share; something about this balloon is not what it looks like, and
        # the older cuts are better placed to guess.
        x, y, w, h = (int(v) for v in r.bbox)
        box = share[max(0, y):y + max(1, h), max(0, x):x + max(1, w)]
        if box.size == 0 or float(box.mean()) < 0.5:
            return {}
        out[r.id] = share * 255
    return out


def _clip_to_box(region, share):
    """`share` trimmed back to this block's own box plus `BOX_LEEWAY`.

    Returns None when the trim leaves nothing that covers the box - a share
    that has to be thrown away is worse than a share that is too generous.

    The neck cut says WHERE a balloon divides. It does not say that a block
    may spread over the whole of its side of the division, and on lee's page
    it does exactly that: the top lobe and the trunk are one piece of paper
    either side of the neck, so a block whose box is up in the lobe letters
    itself down the middle of the trunk and the word lands at the balloon's
    waist. Trimming to the box is what puts it back in the lobe.

    It costs point size - on the two-lobe fixture, 34pt becomes 17 and 25
    becomes 12 - and that is the whole trade. lee: *"that fine the size dnst
    mattaer as long as it in the box"*.

    Unlike `_box_confined` this does NOT then keep the largest connected
    piece. That step is there because the nearest-box cut genuinely
    fragments - it hands out pixels by ownership, and ownership is not
    contiguous. This trim is a share intersected with a dilated rectangle,
    and on every balloon shape tried for it - a ring, a deep wedge, a
    detached tail, a hairline slicing the shoulder off - it either comes back
    in one piece or leaves a crumb the fitter lays out identically either
    way. Code that cannot be told from its own absence does not stay.
    """
    m = (share > 0).astype(np.uint8)
    if not m.any():
        return None
    x, y, w, h = (int(v) for v in region.bbox)
    x0, y0 = max(0, x), max(0, y)
    x1 = min(m.shape[1], x + max(1, w))
    y1 = min(m.shape[0], y + max(1, h))
    if x1 <= x0 or y1 <= y0:
        return None
    seed = np.ones(m.shape[:2], np.uint8)
    seed[y0:y1, x0:x1] = 0
    away = cv2.distanceTransform(seed, cv2.DIST_L2, 3)
    reach = BOX_LEEWAY * max(4.0, float(min(x1 - x0, y1 - y0)))
    cut = (m & (away <= reach).astype(np.uint8))
    if not cut.any():
        return None
    box = cut[y0:y1, x0:x1]
    if box.size == 0 or float(box.mean()) < 0.5:
        return None
    return cut * 255


def _confine_all(regions: list, shares: dict) -> dict:
    """Every share in `shares` trimmed to its own block's box, where that can
    be done at all.

    Per block, not all-or-nothing: one block whose box the trim would not
    cover keeps the share it had, and its neighbours still get theirs trimmed.
    Leaving a whole balloon untrimmed because one block in it is oddly placed
    is how the word ends up at the waist again.

    Known and left alone: this runs AFTER the cut has been chosen, and the cut
    is chosen by measuring the untrimmed shares. So the winner is the best
    division, not necessarily the one that typesets largest once trimmed - on
    the strangled fixture in test_pipeline.py the straight cut wins at 19 and
    20 and comes out at 17 and 13, where the cut down the middle would have
    come out at 16 and 14. One point on the smaller block. Scoring the trimmed
    candidates instead means trimming three candidates per balloon and
    trimming the do-nothing baseline too, or every division starts losing to
    an untrimmed comparison and stops being adopted at all. Not worth one
    point.
    """
    out = dict(shares)
    for r in regions:
        cur = shares.get(r.id)
        if cur is None:
            continue
        got = _clip_to_box(r, cur)
        if got is not None:
            out[r.id] = got
    return out


def _prop_cut(regions: list, masks: list, texts: list,
              vertical: bool = False) -> dict:
    """Cut the union of `masks` into one band per region, sized by how much
    each region has to say.

    `vertical` False stacks the bands one above another; True sets them side by
    side. Which is right depends on the balloon: a tall oval divided across
    gives both blocks its full width, while a balloon built as two lobes wants
    a block in each lobe, and that is a cut down the middle.

    The bands are handed out in the order the JAPANESE sits along the cut, so a
    block always lands on the ink it is replacing. Reading `regions` in the
    order they arrive is not the same thing - `_balloon_groups` returns
    whatever union-find happened to build, which is not a position at all.
    """
    u = np.zeros(masks[0].shape[:2], dtype=np.uint8)
    for m in masks:
        u = np.maximum(u, (m > 0).astype(np.uint8))
    # The detector's cut leaves a hairline of blank pixels between the shares,
    # and it runs across the direction it divided in. Seal it along the axis
    # this cut integrates over - otherwise a band's whole profile reads zero
    # there and the proportion is measured through a slot. One axis only: a
    # round kernel would push the balloon outward at every concavity, and the
    # point here is to divide the shape, not to grow it.
    seal = (1, 19) if vertical else (19, 1)
    u = cv2.morphologyEx(u, cv2.MORPH_CLOSE, np.ones(seal, np.uint8))

    prof = u.sum(axis=0 if vertical else 1).astype(np.float64)
    at = np.flatnonzero(prof)
    if at.size < 40:
        return {}
    a0, a1 = int(at[0]), int(at[-1])
    cum = np.cumsum(prof[a0:a1 + 1])
    total = float(cum[-1])
    if total <= 0:
        return {}
    # bbox is (x, y, w, h): the ink's left edge for a cut down the middle, its
    # top edge for a cut across.
    order = sorted(range(len(regions)),
                   key=lambda i: regions[i].bbox[0 if vertical else 1])
    regions = [regions[i] for i in order]
    texts = [texts[i] for i in order]
    want = np.cumsum([max(1, len(t)) for t in texts], dtype=np.float64)
    want /= want[-1]

    out, start = {}, a0
    for i, r in enumerate(regions):
        end = a1 if i == len(regions) - 1 else \
            a0 + int(np.searchsorted(cum, want[i] * total))
        end = max(start, min(a1, end))
        piece = np.zeros_like(u)
        if vertical:
            piece[:, start:end + 1] = u[:, start:end + 1]
        else:
            piece[start:end + 1] = u[start:end + 1]
        # A share too thin to typeset into means the proportion asked for
        # something this balloon cannot give; leave the whole group alone
        # rather than hand one half a sliver.
        if int(piece.sum()) < 200 or (end - start) < 12:
            return {}
        out[r.id] = piece * 255
        start = end + 1
    return out


def _row_proportional_cut(regions: list, masks: list, texts: list) -> dict:
    """The bands stacked one above another - see `_prop_cut`."""
    return _prop_cut(regions, masks, texts, vertical=False)


def link_masks(regions: list) -> dict:
    """region id -> the shape to typeset into, for the halves of a split line.

    Empty for every page that has no split bubble on it, which is most of
    them. Nothing here is written back to the regions: the polygon a region
    was detected with is what gets saved and reloaded, so a shape invented for
    one typesetting pass must not outlive it.
    """
    out: dict = {}
    for rs in _linked_groups(regions):
        out.update(_stacked_share(rs))
    return out


def _linked_groups(regions: list) -> list:
    """The halves of a split line, grouped by their `link` id."""
    groups: dict = {}
    for r in regions:
        g = int(getattr(r, "link", 0) or 0)
        if g:
            groups.setdefault(g, []).append(r)
    return [rs for rs in groups.values() if len(rs) >= 2]


def _balloon_groups(regions: list) -> list:
    """Regions that were handed shares of ONE balloon, grouped.

    `detect.balloon` already divides a balloon between the blocks inside it and
    takes a hairline off each share, so two shares of one balloon are disjoint
    but a few pixels apart, while two separate balloons are as far apart as the
    page draws them. Closing that hairline and asking what is connected is
    therefore the same question as "did these come out of one balloon", and it
    needs nothing stored on the region to answer.

    Only for a block that is typeset INTO a balloon, though. `attach_balloons`
    hands a balloon to dialogue and narration and to nothing else, on the
    grounds that an effect has no balloon and belongs on the ink's own
    footprint - but free-text detection stores that footprint in the same
    `bubble_mask` field, so an effect arrives here looking exactly like a share
    of a balloon. lee's GRRRR is drawn across the left flank of the balloon
    saying STARING AT A MAN'S BODY LIKE THAT, and the two masks touch; grouped
    together, the balloon is divided BETWEEN them and the dialogue is handed
    the balloon minus a bite out of its left side, which it then centres itself
    in. That is a sound effect moving a line of dialogue, which no typesetter
    would do. So the kinds that never had a balloon are not asked to share one.
    """
    have = [r for r in regions
            if getattr(r, "bubble_mask", None) is not None
            and _kinds.family_of(getattr(r, "kind", "bubble")) == "bubble"
            and (r.dst_text or "").strip()]
    if len(have) < 2:
        return []
    masks = _same_shape_masks(have)
    if masks is None:
        return []
    boxes = [_box_of(m > 0) for m in masks]
    k = np.ones((7, 7), np.uint8)
    grown = [cv2.dilate((m > 0).astype(np.uint8), k) for m in masks]
    parent = list(range(len(have)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(have)):
        for j in range(i + 1, len(have)):
            ax, ay, aw, ah = boxes[i]
            bx, by, bw, bh = boxes[j]
            if (min(ax + aw, bx + bw) - max(ax, bx) < -8 or
                    min(ay + ah, by + bh) - max(ay, by) < -8):
                continue                       # nowhere near each other
            if (grown[i] & grown[j]).any():
                parent[find(i)] = find(j)
    out: dict = {}
    for i, r in enumerate(have):
        out.setdefault(find(i), []).append(r)
    return [g for g in out.values() if len(g) >= 2]


NECK_DENTS = 4            # how many hull dents are paired up looking for a neck
LOBE_KEEPS_ITS_INK = 0.9  # a real neck leaves a block's writing whole


def neck_cuts(mask: np.ndarray, dents: int = NECK_DENTS,
              min_depth: float = 0.0, min_facing: float = 0.0):
    """Every way a balloon's own outline says it is more than one lobe.

    Two overlapping ovals meet at two corners, one on each side of the neck -
    the only two places the outline turns back on itself. So a dent in the
    convex hull is a candidate end of the dividing chord, and the chord between
    two dents is the line the artist would have drawn.

    Which two, though. Taking the deepest pair and stopping is wrong on any
    balloon that also has a TAIL: a tail is a spike sticking out, the hull spans
    it from one side to the other, and the dents it leaves beside it are as deep
    as a neck's or deeper. Most two-lobed balloons have a tail, so the deepest
    pair alone misses most of them.

    So the deepest few dents are paired up and every pair offered in turn, the
    pair whose SHALLOWER dent is deepest first. That is the deepest pair there
    is, which is what was tried before and is still right far more often than
    anything else; what has changed is only that being wrong about it is no
    longer fatal. Ties - and a tail's two dents are usually near enough equal to
    tie - go to the pair spanning the narrower gap, because a neck is a WAIST.

    Nothing about an outline can tell a neck from a tail; only the writing can,
    and this function has never seen the writing. It yields candidates -
    `(labels, count)` straight out of `cv2.connectedComponents` - and the caller
    believes whichever one puts the text where the text actually is.

    `min_depth` is in pixels, and is for callers who have no second opinion to
    fall back on. Any chord across any shape divides it into two, so a caller
    that is asking "is this one balloon or two" - rather than "which of these
    two blocks is where" - has to be told what a dent is first, or a plain oval
    with a hair of anti-aliasing on its rim is a two-lobed balloon.

    `min_facing` is the other half of that, and it is what a waist actually is.
    Where two ovals cross, the outline dives inward from BOTH sides towards the
    same line: dent A points along the chord at dent B, and dent B points back
    along it at dent A. A balloon that is one angular shape - lee's shout
    balloon with a step cut into its left flank - has dents too, but they are
    unrelated: one bites in from the left, the other up from the bottom, and
    the chord between them runs across the balloon rather than through a waist.
    Scoring each dent's inward direction against the chord separates the two,
    and a caller with no writing to check the answer against needs it: this is
    a balloon lee's page shows as one box, and depth alone calls it two.
    """
    m = (mask > 0).astype(np.uint8)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return
    c = max(cnts, key=cv2.contourArea)
    if len(c) < 4:
        return
    try:
        d = cv2.convexityDefects(c, cv2.convexHull(c, returnPoints=False))
    except cv2.error:
        return
    if d is None or len(d) < 2:
        return
    # (N, 1, 4) is what every OpenCV this has been run against hands back, but
    # the middle axis is a formality and reading it as one is not worth a
    # crashed run on a build that drops it. Anything else is not defects.
    d = np.asarray(d)
    if d.ndim == 3:
        d = d[:, 0, :]
    if d.ndim != 2 or d.shape[-1] != 4:
        return
    # convexityDefects reports depth in 1/256ths of a pixel.
    d = [v for v in d if float(v[3]) >= min_depth * 256.0]
    if len(d) < 2:
        return
    deep = sorted(d, key=lambda v: -float(v[3]))[:max(2, int(dents))]
    pts = [tuple(int(z) for z in c[int(v[2])][0]) for v in deep]
    dep = [float(v[3]) for v in deep]
    # Which way each dent bites: from the middle of the hull edge it spans,
    # towards the point it reaches. Unit length, so a dot product against the
    # chord is a cosine.
    inward = []
    for v in deep:
        p = np.asarray(c[int(v[2])][0], dtype=float)
        mid = (np.asarray(c[int(v[0])][0], dtype=float)
               + np.asarray(c[int(v[1])][0], dtype=float)) / 2.0
        step = p - mid
        inward.append(step / max(float(np.hypot(*step)), 1e-6))
    pairs = sorted((-min(dep[i], dep[j]), -(dep[i] + dep[j]),
                    math.dist(pts[i], pts[j]), i, j)
                   for i in range(len(pts)) for j in range(i + 1, len(pts)))
    for *_, i, j in pairs:
        if min_facing > 0.0:
            chord = np.asarray(pts[j], dtype=float) - np.asarray(pts[i], dtype=float)
            span = float(np.hypot(*chord))
            if span < 1.0:
                continue
            chord = chord / span
            if min(float(inward[i] @ chord),
                   float(inward[j] @ -chord)) < min_facing:
                continue
        cut = m.copy()
        cv2.line(cut, pts[i], pts[j], 0, 3)
        # 4-connectivity, and it has to be said by name: the second POSITIONAL
        # argument is the output array, so `4` there is silently discarded and
        # the default 8 used instead - which walks diagonally straight through
        # a cut one pixel at a time and joins the two lobes back together.
        n, lab = cv2.connectedComponents(cut, connectivity=4)
        if n - 1 >= 2:
            yield lab, n


def _ink_sides(regions: list, lab: np.ndarray) -> "Optional[dict]":
    """Which lobe each block's Japanese is in, or None if it is in both.

    A block must keep essentially ALL of its ink - nine tenths - on one side of
    the chord, and no two blocks may claim the same side. A chord that runs
    down the middle of a single lobe fails both ways, which is what tells a
    burst balloon's spikes from a real neck.
    """
    out: dict = {}
    taken: set = set()
    for r in regions:
        if r.text_mask is None:
            return None
        ink = r.text_mask > 0
        total = float(ink.sum())
        hit = lab[ink]
        hit = hit[hit > 0]
        if total <= 0 or not hit.size:
            return None
        v, cnt = np.unique(hit, return_counts=True)
        lb = int(v[int(cnt.argmax())])
        if lb in taken or float(cnt.max()) / total < LOBE_KEEPS_ITS_INK:
            return None
        taken.add(lb)
        out[r.id] = (lab == lb).astype(np.uint8) * 255
    return out


def _lobe_cut(regions: list, masks: list, cfg: TypesetConfig) -> dict:
    """A balloon drawn as two lobes, divided the way it was drawn.

    Two overlapping ovals meet at two corners, one on each side of the neck -
    the only two places the outline turns back on itself. Everywhere else the
    balloon bulges outward. So the deepest pair of dents in its convex hull IS
    the neck, and the chord between them is the line the artist would have
    drawn: one lobe on each side, each holding the block that was written in it.

    This does not have to typeset larger than the proportional cuts to be
    adopted, only close. A cut across or down the middle is a guess at where the
    English should go; lobes are not a guess, they are the page saying it. lee's
    page 013 makes the difference plain - cut down the middle, the first block
    typesets a point bigger but sits jammed against the balloon's right edge with
    the trunk's whole left side empty, because it is centred in its half rather
    than in the oval it belongs to. Its caller keeps this cut over anything that
    is not `NECK_CUT_OVERRULED_AT` times larger; the balloons where it hands a
    block a strip narrower than its longest word are the ones it loses.

    Two things have to hold before that reasoning applies, and on a burst
    balloon neither does. The dents have to be a neck rather than the spikes of
    a jagged outline: page 030's balloon has two 50px defects on opposite
    flanks, and the chord between them runs straight down the middle of one
    single lobe, cutting the first block's own Japanese in half. So each block
    must keep essentially ALL of its ink - nine tenths - on its own side of the
    chord, which the spike cut misses by a mile and a real neck passes exactly.
    And both lobes have to actually hold their text, or the division is a
    finding about the outline that the dialogue cannot live with.
    """
    if len(regions) != 2:
        return {}
    real = np.zeros(masks[0].shape[:2], dtype=np.uint8)
    for m in masks:
        real = np.maximum(real, (m > 0).astype(np.uint8))
    # The detector's hairline between the shares would read as a dent all by
    # itself, and a deeper one than the neck.
    k = np.ones((9, 9), np.uint8)
    u = cv2.morphologyEx(real, cv2.MORPH_CLOSE, k)
    # The bridging is allowed to JOIN the shares and not to GROW the balloon.
    # A close does both, and the second half is what deleted lee's R: it fills
    # every dent in the outline as readily as the gap between the parts - 330px
    # of page 001's balloon, 313 of them handed to the lower lobe along its
    # outer flank, where the fitter then typeset and `render_page`, compositing
    # through the region's own mask, printed nothing. The two are easy to tell
    # apart: a pixel of the seam has BOTH shares within reach, and a pixel of a
    # dent has only the one whose flank it is bitten out of.
    #
    # It is not exact, and the inexactness is worth naming. Where the seam opens
    # onto the balloon's rim, both lobes are within reach of a few pixels just
    # outside the outline and those come in with it: 13 on the fixture that has
    # both a seam and a dent, against the 313 the dent used to bring. They are
    # at the NECK, which is the one part of a balloon no line of type ends at.
    # A smaller kernel closes that gap and opens a worse one - at 5x5 the
    # detector's own hairline stops being bridged, the neck is read in the
    # wrong place, and lee's two-lobed page loses a point of size.
    reach = [cv2.dilate((m > 0).astype(np.uint8), k) for m in masks]
    seam = np.ones(real.shape, bool)
    for d in reach:
        seam &= d > 0
    allowed = (real > 0) | seam
    for lab, n in neck_cuts(u):
        if n - 1 < len(regions):
            continue
        out = _ink_sides(regions, lab)
        if out is None:
            continue                       # a tail, or a chord through a lobe
        # ...back inside the balloon, keeping the seam and dropping the dents.
        out = {i: np.where(allowed, v, 0).astype(v.dtype)
               for i, v in out.items()}
        if all(_lobe_holds(r, out[r.id], cfg) for r in regions):
            return out
    return {}


def _lobe_holds(r, share: np.ndarray, cfg: TypesetConfig) -> bool:
    lay = fit_region(r, cfg, share)
    return bool(lay.lines) and bool(lay.fit_ok)


def _measure(regions: list, shares: dict, cfg: TypesetConfig) -> tuple:
    """What a division is worth: (smallest type it typesets at, how much of its
    own Japanese the worst-served block keeps).

    Size is the first question - a block starved down to 8pt is the failure
    this whole mechanism exists to prevent. But two divisions of the same
    balloon often typeset at exactly the same size and put the words in
    completely different places, and then the second number decides: a block of
    English belongs on top of the Japanese it replaces, not somewhere else in
    the same balloon. `-1` is a division some block cannot fit into at all.
    """
    return _score_cut(regions, shares, cfg)[:2]


def _off_balloon(region: TextRegion, lay: TextLayout, cfg: TypesetConfig,
                 mask: "Optional[np.ndarray]") -> float:
    """The WORST line's share of typesetting that lands off the white, on the art.

    Nothing else in the fitter asks this, because nothing else has to: a line
    is kept inside the BOX around its shape, and for an ordinary balloon the
    box is a fair stand-in for the balloon. For a crescent it is not, and for
    two overlapping balloons the grouping has run together it is not at all -
    lee's page 008 has a pair like that, and a cut straight across them scores
    a beautiful 21pt by laying the first line over the gap between the two.

    The worst line and not the average of them, because a block of dialogue is
    read one line at a time and the reader's eye stops at the one lying across
    the artwork; three clean lines do not make up for it. Averaging is how
    page 008's lower pair got through the gate that was built for exactly it:
    only the last two lines of I'M SORRY. WE HAVE TO BE GETTING BACK. reach
    across into the balloon behind, so 8% on the line lee can see came out as
    4.7% overall - a third of a point under the bar - and the cut that carried
    the dialogue over the neck was adopted as the best available. Measured a
    line at a time the two cases separate cleanly on every balloon to hand: an
    honest fit on a solid balloon loses nothing at all and the worst honest
    case in the chapter loses 4%, while every cut that lays a line over the gap
    between two balloons loses 6% or more.
    """
    shape = mask if mask is not None else region.place_mask()
    if shape is None or not lay.lines:
        return 0.0
    lay = enforce_bounds(region, lay, cfg, mask)
    path = lay.font_path or cfg.font_path
    asc, desc = _font(path, lay.font_size).getmetrics()
    high = asc + desc
    H, W = shape.shape[:2]
    worst = 0.0
    for (cx, cy), line in zip(lay.line_origins, lay.lines):
        wide = _text_w(path, lay.font_size, line)
        x0, x1 = max(0, int(cx - wide / 2)), min(W, int(cx + wide / 2))
        y0, y1 = max(0, int(cy - high / 2)), min(H, int(cy + high / 2))
        if x1 <= x0 or y1 <= y0:
            continue
        sub = shape[y0:y1, x0:x1] > 0
        worst = max(worst, (sub.size - int(sub.sum())) / sub.size)
    return worst


def _score_cut(regions: list, shares: dict, cfg: TypesetConfig) -> tuple:
    """`_measure`, plus how much of the typesetting lands off the balloon."""
    sizes, kept, off = [], 1.0, 0.0
    for r in regions:
        m = shares.get(r.id)
        lay = fit_region(r, cfg, m)
        if not lay.lines:
            return (-1, 0.0, 1.0)
        sizes.append(int(lay.font_size))
        if m is not None and r.text_mask is not None:
            ink = r.text_mask > 0
            n = float(ink.sum())
            if n > 0:
                kept = min(kept, float(((m > 0) & ink).sum()) / n)
        off = max(off, _off_balloon(r, lay, cfg, m))
    return (min(sizes) if sizes else -1, kept, off)


# How much larger another division has to typeset before it is allowed to
# overrule a cut the balloon's own outline asked for, and how much of its own
# Japanese each block has to keep when it does. lee's page 013 - the balloon he
# twice sent back saying the two blocks must stay in their own lobes - is
# beaten by nine percent, which is a typesetter's judgement call. The balloons he
# is complaining about now are beaten by ninety, which anyone can see.
#
# And a division that typesets big by sliding the English clean off the words it
# replaces is not a better division. Three quarters is the floor, not half,
# because of page 008's farewell balloon: cut straight across, the lower band
# spans both lobes and typesets two points larger, and it does it by dragging
# each block off its own lobe and centring it on the whole balloon - which is
# the thing lee has now sent back five times. That cut keeps 62% of each
# block's own writing; the cut on page 030 that genuinely rescues a strangled
# lobe keeps 86%. The gap between them is wide enough to legislate in.
NECK_CUT_OVERRULED_AT = 1.25
NECK_CUT_KEEPS_ITS_OWN = 0.75

# A line drawn along the edge of a curved balloon always clips a little white
# off the corners of its own box, so "on the balloon" cannot mean every pixel.
# A twentieth is the most an honest LINE loses - page 008's widest honest fit
# loses 4% on its worst line - and the cuts that lay a line across the gap
# between two balloons lose 6% to 12% on it.
SPILL_ALLOWED = 0.05


def share_masks(regions: list, cfg: "Optional[TypesetConfig]" = None) -> dict:
    """region id -> the shape to typeset into, for blocks that share a balloon.

    Two blocks in one balloon are divided by where the JAPANESE sat, which is
    the right answer to "whose pixel is this" and often the wrong answer to
    "where does this block of English go". Japanese sets in vertical columns,
    so a second block usually sits alongside the first; English sets in
    horizontal lines, so a typesetter stacks the two blocks and gives each the
    balloon's full width. On lee's page 030 the columns overlap over four
    fifths of their height, so `detect.balloon` divided that balloon down the
    middle and handed the shorter block a 104px strip - narrower than the word
    DISRESPECTFUL...! at any size the fitter is allowed to use, so it fell
    through to the emergency wrap and came out at 8pt beside its neighbour's
    18. Cut straight across instead and the same balloon typesets them at 22
    and 17.

    And sometimes neither is right. lee's page 013 is one balloon drawn as two
    lobes, a tall oval with a rounder one budded off its lower left, and the
    artist put a block in each. Cut across and both blocks centre themselves in
    the trunk, leaving the whole left lobe empty white; the words end up
    nowhere near the Japanese they replace. Cut down the middle instead and
    each block goes back in its own lobe - 17pt on six lines and 16pt on four,
    where the page's own typesetter used about 15 and 10.

    Which cut is right cannot be decided from the ink alone: it depends on how
    much English there is and how the balloon is shaped. So typeset it every way
    and measure. A division that is only ever adopted after it demonstrably
    typesets larger - or typesets just as large while keeping each block on its
    own ink - cannot make any page worse than the geometry it replaces, and
    ties keep the detector's answer.
    """
    if cfg is None:
        return link_masks(regions)
    out: dict = {}
    done: set = set()
    for group in _balloon_groups(regions):
        masks = _same_shape_masks(group)
        if masks is None:
            continue
        done.update(r.id for r in group)
        # Reading the outline is an improvement on the search below, not a
        # prerequisite for it. A balloon whose geometry the reader cannot make
        # sense of must fall through to the search, not take the page's
        # typesetting down with it.
        try:
            lobes = _lobe_cut(group, masks, cfg)
        except Exception:
            lobes = {}
        # More than one block in this balloon, and no neck the artist drew to
        # divide it at? Then each block letters where its own box is. lee:
        # *"the typesetting shoud not be putting text across 2 boxes it shoud
        # never happen - for buble text make it so that teh text goes where teh
        # box is with a little leeway"*.
        #
        # It comes ahead of the bands below, which are the thing that put one
        # block's words across another's box. It comes BEHIND the neck cut,
        # because a balloon the artist drew as two lobes has already answered
        # the same question better: a block in each lobe IS a block where its
        # box is, with the artist's own leeway.
        if len(group) > 1 and not lobes:
            confined = _box_confined(group, masks)
            if len(confined) == len(group):
                out.update(confined)
                continue
        texts = [(r.dst_text or "").strip() for r in group]
        # What every candidate has to beat is the arrangement already in the
        # regions - usually the detector's own division, which is disjoint and
        # perfectly good. But when the blocks claim the same paper it is not a
        # division at all, and it scores brilliantly for the worst possible
        # reason: both blocks letter themselves into the whole balloon, at the
        # size the whole balloon allows, and are printed one through the other.
        # Nothing can beat that, so nothing is ever adopted and the collision
        # survives. So it does not get to stand as a candidate: measure the
        # cuts against nothing, and let any real division win.
        must = _claim_the_same_paper(masks)
        if must:
            best, keep, inside = (0, 0.0, 1.0), {}, False
        else:
            best, keep = _score_cut(group, {}, cfg), {}
            inside = best[2] <= SPILL_ALLOWED
        for vertical in (False, True):
            cand = _prop_cut(group, masks, texts, vertical=vertical)
            if len(cand) != len(group):
                continue
            got = _score_cut(group, cand, cfg)
            # Typesetting that stays on the balloon beats typesetting that does
            # not, at any size. Only then is it a question of how big.
            if (got[2] <= SPILL_ALLOWED) != inside:
                if got[2] <= SPILL_ALLOWED:
                    best, keep, inside = got, cand, True
                continue
            if got[0] > best[0] or (got[0] == best[0] and got[1] > best[1] + 0.02):
                best, keep = got, cand
        if lobes:
            # The neck the artist drew is the best guess at where the balloon
            # divides, so it stands - but it is a guess, not a fact, and on
            # some balloons it hands each block a strip narrower than the words
            # going into it and the page comes out at eleven point beside a
            # neighbour's twenty-two. Let a cut that is plainly larger take it.
            neck = _score_cut(group, lobes, cfg)
            neat = neck[2] <= SPILL_ALLOWED
            beaten = (inside and not neat) or (
                inside == neat
                and best[0] >= neck[0] * NECK_CUT_OVERRULED_AT
                and best[1] >= NECK_CUT_KEEPS_ITS_OWN)
            if not beaten:
                # …trimmed back to the boxes. The neck says WHERE the balloon
                # divides; it does not say a block may spread across the whole
                # of its side of it.
                out.update(_confine_all(group, lobes))
                continue
        if keep:
            out.update(_confine_all(group, keep))
        elif must:
            # Every band was refused and there is no neck to cut at, but these
            # blocks still own the same paper. Anything disjoint beats leaving
            # them to print through each other.
            out.update(_confine_all(group, _nearest_ink_cut(group, masks)))
    # A linked pair the balloon grouping never reached - no bubble mask to
    # group by - still gets the cut it has always had. There is nothing to
    # measure it against there, so nothing to choose between.
    for rs in _linked_groups(regions):
        if not any(r.id in done for r in rs):
            out.update(_stacked_share(rs))
    # THE BALLOON CHECK'S BETTER SHAPE, last and lowest. When the saved
    # outline runs off its balloon, `balloonck` writes the model's balloon as
    # `fit_poly` - for the TYPESETTER only, at lee's word: *"it should only
    # help the typesetter on bubble text"*. It lands here because this dict is
    # the one thing every fitting path reads (the page fit, `_level_caps`'
    # probe, and the editor's per-box preview at `editor.layout_preview`), so
    # preferring it anywhere else would fit the page one way and preview it
    # another. A block whose balloon is genuinely shared is already in `out`
    # and keeps its cut - the check never writes `fit_poly` onto a balloon
    # holding more than one box, and this line could not override a share
    # anyway.
    for r in regions:
        if r.id not in out and getattr(r, "fit_poly", None)                 and _kinds.family_of(r.kind) == "bubble":
            m = _mask_from_poly(r.fit_poly, regions)
            if m is not None:
                out[r.id] = m
    return out


def _mask_from_poly(poly, regions):
    """`fit_poly` as a page-sized mask, sized from any mask on the page."""
    import cv2 as _cv2
    shape = None
    for r in regions:
        for m in (r.bubble_mask, r.text_mask, r.share_mask):
            if m is not None:
                shape = m.shape[:2]
                break
        if shape:
            break
    if not shape or not poly or len(poly) < 3:
        return None
    out = np.zeros(shape, np.uint8)
    _cv2.fillPoly(out, [np.asarray(poly, np.int32).reshape(-1, 1, 2)], 255)
    return out


SFX_ROOM = 0.55        # ...but not at the price of more than this much size


def _keep_off_the_sound_effects(page, shares: dict) -> None:
    """Take the sound effects out of the room the dialogue is offered.

    lee, with a crop of COUGH printed straight through "...THIS MUCH IS ONLY
    NATURAL!": *"make the typesetter use a the image that i see to typeset"*.

    Every block is fitted against its own area and told nothing about any
    other, so a page where two of them want the same paper prints one through
    the other. Between two speech balloons that cannot happen - a balloon is
    drawn round its own words - but a sound effect has no balloon, is drawn
    over the artwork wherever the original mark was, and is not clipped to
    anything. It cannot move. The dialogue can, so the dialogue is the one
    told.

    The BOX and not the fitted ink, because the fitting has not happened yet
    and the box is where `fit_sfx_region` centres the effect anyway. And only
    when it is cheap: a big effect across the middle of a balloon leaves a
    shape nothing sets well in, and dialogue at half the size to avoid a
    collision is a worse page than dialogue with a collision. `SFX_ROOM` is
    the share of its room a block may lose to this.
    """
    sfx = [r for r in page.regions
           if _kinds.family_of(r.kind) == "sfx" and (r.dst_text or "").strip()]
    if not sfx:
        return
    shape = None
    for r in page.regions:
        m = shares.get(r.id)
        if m is None:
            m = r.place_mask()
        if m is not None:
            shape = m.shape[:2]
            break
    if shape is None:
        return
    keep_off = np.zeros(shape, np.uint8)
    for s in sfx:
        x, y, w, h = (int(v) for v in (s.bbox or (0, 0, 0, 0)))
        if w < 2 or h < 2:
            continue
        keep_off[max(0, y):y + h, max(0, x):x + w] = 1
    if not keep_off.any():
        return
    off = keep_off > 0
    for r in page.regions:
        if _kinds.family_of(r.kind) == "sfx":
            continue
        m = shares.get(r.id)
        if m is None:
            m = r.place_mask()
        if m is None:
            continue
        was = m > 0
        n = int(was.sum())
        if not n:
            continue
        left = was & ~off
        if int(left.sum()) == n:
            continue                       # nothing of this one is wanted
        if int(left.sum()) < SFX_ROOM * n:
            continue                       # too much of the balloon to give up
        shares[r.id] = np.where(left, 255, 0).astype(np.uint8)


# ------------------------------------------------- one size across one page

# How far above the page's own size a block of dialogue may sit.
#
# Swept rather than picked (`his/band.py`): every candidate typesets lee's
# whole chapter, renders it, and scores it through the same detector and the
# same arithmetic as the professional chapter, against the two numbers measured
# there - fill 0.382, spread 1.33x, middle half +/-15%.
#
#     band     fill   spread   middle half
#     off     0.549     1.91      0.21
#     1.05    0.485     1.42      0.11
#     1.10    0.502     1.46      0.15     <-
#     1.15    0.505     1.54      0.16
#     1.30    0.526     1.67      0.19
#     1.50    0.538     1.74      0.20
#     1.75    0.547     1.79      0.21
#
# 1.10 puts the middle half exactly where the professional's is. Tighter is
# not better: 1.05 comes out at 0.11, which is MORE even than the people who
# do this for a living, and a page whose every balloon is the same size to
# within a twentieth reads as set by a machine, because it was.
#
# The spread is still 1.46 against their 1.33, and no band closes that: a band
# is a ceiling, and what is left is the FLOOR - blocks that are small because
# one long word is their whole ceiling. That is hyphenation's half of the job,
# not this one's.
LEVEL_BAND = 1.10

# Fewer blocks than this and there is no such thing as "the size on this page":
# three balloons of which one is a shout has a median that means nothing.
LEVEL_MIN = 4


def _level_caps(page, cfg: TypesetConfig, shares: dict):
    """The size this page is set at, and a ceiling for whatever overshoots it.

    lee, twice: *"try to make teh typesetting more constsant and better fit the
    boxes"*. I did the second half and argued the first half away - levelling
    two adjacent boxes means pulling one DOWN, which is less well filled, so
    the two halves looked like opposites and I would not choose between them on
    a hunch.

    Then he sent the published English chapter 22 beside the Japanese it was
    made from. Measured with one instrument - our detector over both, our
    arithmetic over both - the halves are not opposites at all:

                            professional      ours
        block / balloon          0.38         0.55
        biggest / smallest       1.33x        1.91x
        middle half             +/-15%       +/-21%

    We were already filling balloons HALF AGAIN as full as the people who do
    this for a living, and the thing we were not doing was keeping the letters
    the same size. A professional takes 0.38 to get 1.33x. That is not a
    conflict between the two things lee asked for; it is the answer to them.

    So: the page's median dialogue size is what the page is set at, and a block
    fitted more than `LEVEL_BAND` above it is fitted again with that ceiling.
    Only downward - a block is small because its balloon is small, and forcing
    one up is how a line ends up outside the shape it was clipped to.

    Sound effects are not dialogue and are not levelled: their size is drawn
    from the mark they replace, and the professional's 1.33x is measured with
    them excluded too. Neither is anything set by hand - a size somebody typed
    is not an accident to be tidied.

    Returns `(probe, caps)`: the fit each block came to on its own, so the
    blocks that are already inside the band are not fitted a second time, and
    the ceiling for the ones that are not.
    """
    probe, sizes = {}, []
    for r in page.regions:
        if not r.dst_text or _kinds.family_of(r.kind) == "sfx":
            continue
        if (r.layout_override or {}).get("locked"):
            continue
        was = r.dst_text
        if (r.layout_override or {}).get("caps"):
            r.dst_text = r.dst_text.upper()
        try:
            lay = fit_region(r, cfg, shares.get(r.id))
        finally:
            r.dst_text = was
        if lay is None or not lay.lines or not lay.font_size:
            continue
        probe[r.id] = lay
        sizes.append(float(lay.font_size))
    if len(sizes) < LEVEL_MIN:
        return probe, {}
    # Never below the floor: a ceiling under `min_font` is a ceiling nothing
    # can be fitted beneath, and the block would come back empty.
    cap = max(int(cfg.min_font),
              int(round(LEVEL_BAND * float(np.median(sizes)))))
    return probe, {rid: cap for rid, l in probe.items() if l.font_size > cap}


# The override keys that decide WHERE THE LINES LAND, as opposed to what
# colour they are. Everything `layout_from_override` and the fitter read, and
# nothing else - so changing a colour or a glow does not throw a page's fitting
# away and make it again. Kept as one list because `page_fit_key` and anybody
# reasoning about it need to be looking at the same one.
FIT_KEYS = ("caps", "dx", "dy", "fit", "fixed", "font", "font_size", "frame",
            "leading", "lines", "locked", "lspace", "origins", "rotate",
            "snug", "stroke", "wrap")


# The last few pages' fitting, by the key it was fitted under.
#
# The stamp on the record is the durable half of this and it is written when a
# page is COMMITTED - by the Typeset button, by a save. Plenty of renders never
# commit: the exact view asks read-only on purpose, and a render served from
# the disk cache never lays anything out at all, so it never stamps either. On
# those pages the stamp is missing and every rebuild fitted from scratch -
# which is most of them while somebody is editing, because changing a COLOUR
# rebuilds the picture without changing anything about the fit.
#
# So the fitting is also remembered here, for the length of the run. Small -
# the layouts of a couple of dozen pages - and keyed by exactly the thing that
# decides them, so a hit is the answer the fitter would have given.
_FITS: "OrderedDict[str, dict]" = OrderedDict()
FIT_CACHE_MAX = 24

# The SHARE CUTS, remembered under the same key. `share_masks` is not the
# 40ms of geometry its name suggests: deciding how to divide a shared balloon
# TYPESETS THE CANDIDATES AND MEASURES ("typeset it every way and measure" -
# its own words), which on a page with linked balloons is the fitter run ten
# times over. It sat ABOVE the fit-cache early return, so every render of an
# unchanged page paid it - three seconds here, ten on lee's machine, and it
# was the whole of *"its taking a good 10s secor or more to rebuild"*.
# Masks are page-sized, so they are kept PNG-encoded (~10-30KB each) and
# decoded on recall, which is milliseconds.
_SHARES: "OrderedDict[str, list]" = OrderedDict()
SHARE_CACHE_MAX = 12


def _remember_shares(key: str, shares: dict) -> None:
    import cv2 as _cv2
    packed = []
    for rid, m in shares.items():
        if m is None:
            continue
        ok, buf = _cv2.imencode(".png", m)
        if ok:
            packed.append((rid, buf.tobytes()))
    _SHARES[key] = packed
    _SHARES.move_to_end(key)
    while len(_SHARES) > SHARE_CACHE_MAX:
        _SHARES.popitem(last=False)


def _recall_shares(key: str):
    import cv2 as _cv2
    got = _SHARES.get(key)
    if got is None:
        return None
    _SHARES.move_to_end(key)
    out = {}
    for rid, raw in got:
        m = _cv2.imdecode(np.frombuffer(raw, np.uint8), _cv2.IMREAD_GRAYSCALE)
        if m is None:
            return None                 # a torn entry is no entry
        out[rid] = m
    return out


def _remember_fit(key: str, page) -> None:
    if not key:
        return
    _FITS[key] = {int(r.id): copy.deepcopy(r.layout)
                  for r in page.regions if getattr(r, "layout", None)}
    _FITS.move_to_end(key)
    while len(_FITS) > FIT_CACHE_MAX:
        _FITS.popitem(last=False)


def _recall_fit(key: str, page) -> bool:
    """Put a remembered fitting back on this page. All of it or none."""
    got = _FITS.get(key)
    if not got:
        return False
    want = [r for r in page.regions if r.dst_text]
    if not want or any(int(r.id) not in got for r in want):
        return False
    for r in page.regions:
        lay = got.get(int(r.id))
        if lay is not None:
            r.layout = copy.deepcopy(lay)
    _FITS.move_to_end(key)
    return True


def _all_fitted(page, key: str) -> bool:
    """Does every block that has words already carry a layout fitted under
    `key`? All of them or none: they are fitted against each other."""
    got = False
    for r in page.regions:
        if not r.dst_text:
            continue
        lay = getattr(r, "layout", None)
        if lay is None or getattr(lay, "fit", "") != key:
            return False
        if not (lay.lines or lay.frame):
            return False        # nothing to draw: fit it and find out why
        got = True
    return got


def page_fit_key(page, cfg: "TypesetConfig") -> str:
    """A fingerprint of everything on this page that decides a fit.

    Typesetting a page is 2.6 of the 3 seconds it takes to build one, and it
    was being paid on every render, every export and every restart - because
    `region_from_record` deliberately dropped the stored layout and every
    stage laid the page out again from scratch. That is the right default and
    the wrong price: laying out again is only necessary when something that
    decides the layout has moved.

    So each layout carries the key it was fitted under, and a page whose key
    still matches uses the layouts it already has. What is in it:

    * the whole PAGE, not one block. Blocks are fitted against each other -
      `share_masks` cuts a shared balloon between two of them and `_level_caps`
      sets one size across the page - so one box moving can change where every
      other block's lines land. One key for the page, and it is coarse on
      purpose.
    * the settings that steer the fitter, and not the ones that only steer the
      paint. `FIT_KEYS`, and see the note on it.
    * nothing that is itself an OUTPUT of fitting. The key would then change
      every time it was used.

    A mismatch, or no key at all, means fit as before. It can only ever be as
    wrong as a stale fingerprint, and the fingerprint is over the inputs.
    """
    import hashlib
    import json
    bits = [
        cfg.font_path, sorted((cfg.fonts or {}).items()),
        int(cfg.min_font), int(cfg.max_font), bool(cfg.uppercase),
        bool(cfg.substitutes), bool(getattr(cfg, "strict_containment", False)),
        round(float(getattr(cfg, "compact_margin", 0) or 0), 4),
    ]
    for r in sorted(page.regions, key=lambda r: int(r.id)):
        ov = r.layout_override or {}
        bits.append((
            int(r.id), str(r.kind),
            tuple(int(v) for v in (r.bbox or ())),
            tuple(int(v) for v in (r.bubble_bbox or ())),
            # the SHAPE, not the mask: a mask is page-sized and the polygon is
            # what it is drawn from.
            tuple(tuple(int(a) for a in pt) for pt in (r.polygon or ())),
            # ...and the balloon check's better shape, which moves lines as
            # surely as the outline does.
            tuple(tuple(int(a) for a in pt)
                  for pt in (getattr(r, "fit_poly", None) or ())),
            r.dst_text or "", r.dst_compact or "",
            int(getattr(r, "link", 0) or 0),
            int(getattr(r, "box_group", 0) or 0),
            round(float(getattr(r, "angle", 0.0) or 0.0), 2),
            bool(getattr(r, "sfx_vertical", False)),
            round(float(getattr(r, "sfx_len", 0.0) or 0.0), 3),
            round(float(getattr(r, "sfx_wid", 0.0) or 0.0), 3),
            round(float(getattr(r, "turn", 0.0) or 0.0), 2),
            # A HAND-PLACED BOX IS ONE WORD IN THE KEY, not its whole
            # override. A locked override with its lines carried is rebuilt
            # from the override on every path (`layout_from_override`) and
            # never enters the fitter - and `_level_caps` skips locked
            # regions, so nothing about it can move anyone else's lines.
            # Folding its frame and dx/dy into the key meant every DRAG threw
            # the whole page's fitting away and lee watched "building the
            # exported page..." for seconds per nudge: *"is there a way to
            # make building teh exprted page be faster when i move
            # something"*. Now a move re-places one box and re-uses the rest.
            (("locked",) if (ov.get("locked")
                             and ov.get("lines") is not None) else
             tuple((k, json.dumps(ov[k], sort_keys=True, default=str))
                   for k in FIT_KEYS if k in ov)),
        ))
    return hashlib.sha1(repr(bits).encode("utf-8")).hexdigest()[:16]


def typeset_page(page, cfg: TypesetConfig | None = None,
                 redo: bool = False) -> None:
    """Typeset every region on the page.

    `redo` is the Typeset button: lay the page out again from scratch, hand
    corrections included. Without it (rendering a preview, writing an export)
    the page is typeset as it stands, so looking at a page or exporting one
    never quietly discards work.
    """
    cfg = cfg or TypesetConfig()
    if not cfg.font_path:
        cfg.font_path = default_font_path()
    if redo:
        # Before the masks are cut, so a region freed here is measured with
        # the rest of the balloon rather than around its own old frame.
        for r in page.regions:
            clear_fitting(r)
    # The key FIRST, because the share cuts are remembered under it. It is
    # built from the regions and the config alone, so nothing below feeds it.
    key = page_fit_key(page, cfg)
    shares = _recall_shares(key)
    if shares is None:
        shares = share_masks(page.regions, cfg)
        _keep_off_the_sound_effects(page, shares)
        # AFTER the sound effects took their bite, so what is remembered is
        # what the fits actually used.
        _remember_shares(key, shares)
    # Told to the region, so that whatever renders this page next clips the
    # words with the shape they were fitted into. Everything that draws
    # typesetting typesets first, so this is always the current answer.
    for r in page.regions:
        r.share_mask = shares.get(r.id)

    # ...AND IF NOTHING THAT DECIDES A FIT HAS MOVED, THE FIT ALREADY EXISTS.
    #
    # Everything below this line is the fitter: `_level_caps` alone probes
    # every block on the page and is 2 of the 2.6 seconds a page costs. It was
    # being run on every render, every export and every restart, to arrive at
    # the layouts already sitting on the record.
    #
    # lee: *"make it so that teh typesettng is setting every time i swtitch
    # pages - it shoud do it one and when i switch it shou ld already be
    # teher"*.
    #
    # The shares above are still worked out, because the renderer clips with
    # them and they are 40ms, not 2600. Only the fitting is skipped, and only
    # when every block that has words carries a layout stamped with this
    # page's current key. One missing or stale stamp and the whole page is
    # fitted, because blocks are fitted against each other.
    if not redo and (_all_fitted(page, key) or _recall_fit(key, page)):
        # HAND-PLACED BOXES ARE RE-PLACED, not reused: their overrides are
        # one word in the key (above), so the stored layout may be the box
        # where it stood BEFORE the drag. `layout_from_override` is
        # milliseconds - it is the fitter this path skips, not the placing.
        placed = True
        for r in page.regions:
            ov = r.layout_override or {}
            if not (ov.get("locked") and ov.get("lines") is not None
                    and r.dst_text):
                continue
            _was = r.dst_text
            if ov.get("caps"):
                r.dst_text = r.dst_text.upper()
            manual = layout_from_override(r, cfg, shares.get(r.id))
            r.dst_text = _was
            if manual is None:
                placed = False           # not answerable here: fit for real
                break
            _shape = getattr(getattr(page, "image", None), "shape", None)
            if _shape is not None:
                manual = keep_on_page(manual, cfg, _shape)
            manual = apply_align(manual, cfg,
                                 str(ov.get("align") or "center"))
            manual.fit = key
            r.layout = manual
        if placed:
            # THE COLOURS ARE NOT PART OF THE FIT and must still be worked
            # out. They are read off the PAGE, which is why they are not in
            # `page_fit_key` and why a change of colour does not throw a
            # fitting away. The first version of this returned here and
            # skipped `assign_colours`, so a reused layout kept whatever
            # colours it was carrying: a plain white balloon came back with
            # white letters on it.
            # `test_an_ordinary_white_balloon_stays_black_on_white` said so.
            from . import render as _render
            _render.assign_colours(page, cfg)
            return
    # What size this page is set at, worked out across all of its dialogue
    # before any single block is committed to. `probe` is each block's own fit,
    # kept so that the ones already inside the band are not fitted twice.
    probe, caps = _level_caps(page, cfg, shares)
    for r in page.regions:
        if r.dst_text:
            # ALL CAPS for THIS block. Capitals are wider, so they go on
            # before the fit rather than over the top of one - uppercasing a
            # finished layout is how a line ends up past the edge of its
            # balloon. The project-wide switch (`cfg.uppercase`) still applies
            # to everything; this is one block saying so for itself.
            _was_text = r.dst_text
            if (r.layout_override or {}).get("caps"):
                r.dst_text = r.dst_text.upper()
            share = shares.get(r.id)
            manual = None
            if (r.layout_override or {}).get("locked"):
                manual = layout_from_override(r, cfg, share)
            if manual is not None:
                fresh = manual
            elif r.id in caps:
                # Over the page's size: fitted again under the ceiling.
                fresh = fit_region(r, replace(cfg, max_font=caps[r.id]), share)
                if fresh is None or not fresh.lines:
                    fresh = probe.get(r.id)     # nothing fits under it: leave be
            else:
                fresh = probe.get(r.id)
                if fresh is None:
                    fresh = fit_region(r, cfg, share)
            # Typesetting already on the page is never traded for typesetting that
            # shows nothing. Whatever the reason - a font that cannot draw the
            # words, a mask that came back empty - the run before this one put
            # something readable in the bubble and this one did not, so the
            # bubble keeps what it had. That is what stops a change of font
            # from emptying a page that was already typeset.
            # ...unless the person emptied it on purpose. `manual` is a hand
            # edit, and a hand edit that clears the box is still an edit.
            if (manual is None and not shows_text(fresh)
                    and shows_text(r.layout)):
                continue
            r.layout = fresh
            if r.layout and manual is None:
                # A rotation set by hand wins. Otherwise whatever the fit
                # worked out stays put: overwriting this unconditionally is
                # what threw a sound effect's measured angle away and set it
                # bolt upright on a page where nothing else was.
                ov_rot = (r.layout_override or {}).get("rotate")
                if ov_rot not in (None, ""):
                    r.layout.rotate = float(ov_rot)
            if manual is not None:
                r.flagged = None
            if r.layout and not r.layout.font_path:
                r.layout.font_path = font_for(cfg, r.kind) or cfg.font_path
            # Text you have placed yourself is not pulled back into the
            # region. Clamping it there is what made moving and rotating look
            # like they did nothing. A sound effect is free for the same
            # reason: it is laid out along its own axis, and clamping it to
            # the region squared a leaning effect back up.
            #
            # Every block now carries a frame, so "has a frame" no longer says
            # anything about whether it was placed by hand - asking that
            # question of the frame is how strict containment quietly stopped
            # containing anything at all.
            # A block that is deliberately bigger than its box is NOT
            # listed here. It refuses the clamp inside `enforce_bounds`
            # itself, where the rule can be stated once and measured on its
            # own; a third clause here said the same thing a second time and a
            # mutant could not tell it from its own absence.
            free = manual is not None or _kinds.family_of(r.kind) == "sfx"
            # Two blocks in one balloon: each goes back over its own box.
            # Before the bounds check, because this is a move and that is the
            # thing that guarantees a move stayed on the paper.
            if (r.layout and not free and share is not None
                    and _kinds.family_of(r.kind) != "sfx"):
                r.layout = pull_to_box(r, r.layout, cfg, share)
            if r.layout and cfg.strict_containment and not free:
                r.layout = enforce_bounds(r, r.layout, cfg, share)
            # Last: the box the words actually occupy, and the lines placed
            # from it. Everything downstream - the browser's preview, the box
            # you type into, the export - fills a box the same way, so from
            # here on there is one answer to where a line goes.
            if r.layout and _kinds.family_of(r.kind) != "sfx" and manual is None:
                r.layout = anchor_to_frame(r.layout, cfg)
            # Out of the box is allowed; off the page is not. AFTER the frame
            # is settled, because `anchor_to_frame` rebuilds both the frame and
            # the line positions from scratch and would throw away a slide made
            # before it.
            # EVERY layout, not only the ones marked as leaving their box.
            # lee, with CLACK hanging off the right margin: *"a text shoud
            # never be set outside of the page like this"*. A sound effect is
            # never marked as spilling - the clamp is its authority and it is
            # measured against its own footprint, not the page - so nothing at
            # all was keeping one on the paper. For a block already inside the
            # page this is arithmetic that comes to zero and returns the same
            # layout, so it costs the other several thousand regions nothing.
            #
            # A page with no artwork loaded has no edges to respect - the
            # typesetting panel lays out against geometry alone - so there is
            # nothing to do and nothing to measure against.
            _shape = getattr(getattr(page, "image", None), "shape", None)
            if r.layout and _shape is not None:
                r.layout = keep_on_page(r.layout, cfg, _shape)
            # ...and then hang the lines off whichever edge was asked for.
            # After the frame is settled, because the frame is what they are
            # measured against.
            if r.layout:
                r.layout = apply_align(
                    r.layout, cfg, str((r.layout_override or {})
                                       .get("align") or "center"))
            # The capitals were for laying out, not a rewrite of the
            # translation: what the person typed is what is stored.
            r.dst_text = _was_text

    # And the colours, recorded onto the layouts.
    #
    # The exporter works its colours out afresh every time it draws, so an
    # exported page has always been right. The BROWSER cannot do that - it has
    # no page to look at - so it typesets from `layout.fg`/`edge`/`stroke`, and
    # nothing was ever writing them. They sat at the dataclass defaults, black
    # on white, and every bubble in the editor came out black with a thin white
    # halo no matter what it was standing on. On a dark panel that is invisible
    # typesetting, which is exactly the screenshot lee keeps sending back.
    #
    # Imported here rather than at the top because `render` imports this
    # module; by the time anyone lays a page out, both are loaded.
    from . import render as _render
    _render.assign_colours(page, cfg)

    # ...and last, the key every one of these layouts was fitted under, so the
    # next render of an unchanged page can use them instead of doing all of
    # this again. See `page_fit_key` and the early return above.
    for r in page.regions:
        if getattr(r, "layout", None) is not None:
            r.layout.fit = key
    _remember_fit(key, page)
