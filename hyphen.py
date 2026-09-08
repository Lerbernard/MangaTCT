# -*- coding: utf-8 -*-
"""Where an English word may be broken across two lines.

lee sent the published English chapter 22 as an example of *"how proper
tysetting is doen"*, and one of the things it does that we never did is break
ordinary words: `IDLE TRANS-/FIGURA-/TION`, `BEING TRANS-/FIGURED`. Our fitter
would rather set a whole word small in an empty balloon.

Read off the pages with tesseract, a professional breaks a word at the end of
**2.3 lines in every 100** (7 of 302 in that chapter). lee: *"i dont wanta buch
of hypers everywhere"*. So this module answers only *where a break is allowed*;
how rarely one is taken is `typeset.py`'s business.

## Where the patterns come from

Frank Liang's algorithm, and the English pattern set that has been in TeX since
1983 and in every word processor since. `hyph_en_US.dic` is the LibreOffice
build of it, taken from **pyphen 0.18.1**, which is licensed GPLv2+ / LGPLv2+ /
MPL 1.1 - and GPLv2-or-later is compatible with this app's GPL-3.0.

Vendored rather than depended on. It is 106KB beside model files measured in
hundreds of megabytes, and an editor somebody runs on their own machine should
not need a package index to break a word.

## The algorithm, in one paragraph

Every pattern is a run of letters with digits wedged between them - `a2ch4`,
`.ad4der` - where `.` is the edge of the word. Lay each pattern over the word
wherever its letters match, and at each gap between two letters keep the
LARGEST digit any pattern put there. An ODD number means a break is allowed;
even means it is not. Odd beats even by being larger, so a pattern that forbids
(`2`) is overruled by one that permits more strongly (`3`), which is how the
exceptions to a rule are written in the same language as the rule.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache

_DICT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "hyph_en_US.dic")

# The file's own words for "never leave fewer than this many letters". Read
# from it rather than written here: they belong to the pattern set, and a
# different language's file says something different.
_LEFT, _RIGHT = 2, 3

_PATTERNS: dict | None = None


def _load() -> dict:
    """The pattern set, as `{letters: [digits]}`."""
    global _PATTERNS, _LEFT, _RIGHT
    if _PATTERNS is not None:
        return _PATTERNS
    pats: dict[str, list[int]] = {}
    try:
        with open(_DICT, encoding="utf8", errors="ignore") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("%"):
                    continue
                if line.upper().startswith("LEFTHYPHENMIN"):
                    _LEFT = int(line.split()[-1])
                    continue
                if line.upper().startswith("RIGHTHYPHENMIN"):
                    _RIGHT = int(line.split()[-1])
                    continue
                if line.upper().startswith(("COMPOUND", "UTF-8", "ISO",
                                            "NOHYPHEN")):
                    continue
                # A compound rule (`a1bc=d`) is a different feature - where to
                # break a word that ALREADY has a hyphen in it. Not this.
                if "=" in line or "'" in line:
                    continue
                if not re.fullmatch(r"[.a-z0-9]+", line):
                    continue
                letters = re.sub(r"\d", "", line)
                if not letters:
                    continue
                # One slot per gap, including the two ends.
                vals = [0] * (len(letters) + 1)
                at = 0
                for ch in line:
                    if ch.isdigit():
                        vals[at] = max(vals[at], int(ch))
                    else:
                        at += 1
                pats[letters] = vals
    except OSError:
        pats = {}
    _PATTERNS = pats
    return pats


@lru_cache(maxsize=8192)
def points(word: str) -> tuple:
    """Every position in `word` where it may be broken.

    A position `i` means the break goes between `word[i-1]` and `word[i]`, so
    `word[:i] + "-"` is the first line. Positions are on the word as given, so
    they can be used against the original capitals.
    """
    pats = _load()
    if not pats:
        return ()
    w = word.lower()
    if not w.isalpha() or len(w) < _LEFT + _RIGHT:
        return ()
    padded = "." + w + "."
    # One slot per gap in the padded word.
    vals = [0] * (len(padded) + 1)
    for i in range(len(padded)):
        for j in range(i + 1, len(padded) + 1):
            got = pats.get(padded[i:j])
            if got is None:
                continue
            for k, v in enumerate(got):
                if v > vals[i + k]:
                    vals[i + k] = v
    # Slot k of the padded word sits before `padded[k]`; the leading "." shifts
    # everything by one.
    out = []
    for i in range(_LEFT, len(w) - _RIGHT + 1):
        if vals[i + 1] % 2:
            out.append(i)
    return tuple(out)


def split(word: str, at: int) -> tuple:
    """`word` broken at `at`: the first line WITH its hyphen, and the rest."""
    return word[:at] + "-", word[at:]
