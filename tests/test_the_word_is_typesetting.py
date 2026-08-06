"""lee: *"never use teh word lettering ever againg typessting shud be use"*.

An earlier sweep caught the NOUN and left the verb standing in 56 places,
including the headline on the front of the website, which read "Translate,
clean and letter a chapter". So this one is about the verb.

Two things make it hold where the last one did not.

**Each file is read as ONE LONG LINE.** A phrase that straddles a wrap —
`there is to\n    # letter` — is invisible to a search that works line by line,
and comments in this codebase wrap constantly.

**The glyph sense is allowed on purpose.** A page still has letters on it, a
font still has letter gaps, and a name can still be one letter off the sheet.
Banning the word outright would be a test nobody could keep, and a test nobody
can keep gets deleted rather than obeyed.
"""
import re

import pytest

from where import PKG

SKIP = {"node_modules", "__pycache__", ".pytest_cache", ".firebase", "out",
        "models", "detect", "fonts", "_to_delete", ".git", "assets"}
EXT = {".py", ".js", ".html", ".css", ".md"}

# Two files are allowed to say it, and both for the same reason: their content
# is the wrong version on purpose. This one has to name what it forbids, and
# `tools/mutate.py` holds the mutation that puts the word BACK — which is the
# test of this test, and would be unwritable under its own rule.
SAYS_IT_ON_PURPOSE = {"test_the_word_is_typesetting.py", "mutate.py"}

# The verb, and the two nouns built off it. Everything here means the act of
# putting the English on the page, which is TYPESETTING.
FORBIDDEN = re.compile(
    r"\bletterings?\b"
    r"|\bletterers?\b"
    r"|\bre-?letters?\b"
    r"|\bun-?letters?\b"
    r"|\b(?:to|must|cannot|would|never|should|and|or)\s+letter\b(?!\s+(?:gaps?|by\s+letter|off|from\s+\"))"
    r"|\bletters\s+(?:the\s+page|a\s+chapter|it\s+small|them\s+at|bigger|larger)\b",
    re.I)


def _sources():
    for p in sorted(PKG.rglob("*")):
        if not p.is_file() or p.suffix not in EXT:
            continue
        if any(part in SKIP for part in p.parts):
            continue
        if p.name in SAYS_IT_ON_PURPOSE:
            continue
        yield p


def _one_long_line(text: str) -> str:
    """The whole file with every wrap closed up.

    Not `text.replace("\\n", " ")` alone: a comment that wraps carries a `#` or
    a `*` onto the next line, and "there is to\\n    # letter" has to read as
    "there is to letter" or the phrase hides behind the marker.
    """
    out = re.sub(r"\n\s*(?:#+|//+|\*+)?\s*", " ", text)
    return re.sub(r"\s+", " ", out)


def test_nothing_letters_anything():
    bad = []
    for p in _sources():
        line = _one_long_line(p.read_text(encoding="utf-8", errors="ignore"))
        for m in FORBIDDEN.finditer(line):
            bad.append("%s: …%s…" % (p.relative_to(PKG),
                                     line[max(0, m.start() - 40):m.end() + 40]))
    assert not bad, "\n".join(bad[:40])


def test_the_glyph_sense_is_still_allowed():
    """A page has letters on it, a font has letter gaps, and a name can be one
    letter off the sheet. A rule that banned those would be unkeepable, and an
    unkeepable rule gets deleted rather than obeyed."""
    for ok in ("the letters keep their own colour",
               "the line and letter gaps",
               "a name one letter off the sheet",
               "letter by letter",
               "Letters, numbers, dot, dash and underscore only",
               "that font has no letters in it"):
        assert not FORBIDDEN.search(ok), ok


def test_a_phrase_that_straddles_a_wrap_cannot_hide():
    """The thing the last sweep's test could not see, and the reason 56 of
    these survived it."""
    wrapped = "much there is to\n    # letter. Five lines of it\n"
    assert not FORBIDDEN.search(wrapped), "line by line, it is invisible"
    assert FORBIDDEN.search(_one_long_line(wrapped)), \
        "closed up, it must be found"
    # ...and the same through a JS comment and a Markdown bullet.
    for marker in ("//", "*", ""):
        assert FORBIDDEN.search(_one_long_line(
            "the page and\n  %s letters the page\n" % marker)), marker


def test_the_headline_on_the_website_says_typeset():
    """The one that was on the front of the site for a week."""
    for name in ("index.html", "mangatct-site-standalone.html"):
        html = (PKG / "site" / name).read_text(encoding="utf-8")
        assert "Translate, clean and typeset a chapter" in html, name
        assert "clean and letter a chapter" not in html, name
