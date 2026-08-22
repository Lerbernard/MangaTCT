"""A licence file, because "free" with nothing written down is all-rights-reserved.

lee, on what this is going to be: *"the software itself willmbe free and teh
only part tht is ai will be teh ai related thing s not teh deeting apart"* --
then, shown that the project had no licence file at all: *"do that"*.

Two things this guards.

**GPL-3.0 is not a preference, it is what the foundations already are.**
comic-text-detector is GPL-3.0 and every detection route uses its `seg` head
for the ink mask -- `inpaint` skips any region whose `text_mask is None`, three
times over -- so there has never been a build of this that did not link
copyleft code. manga-image-translator's DBNet and the AnimeText weights are
GPL-3.0 too.

**And the model files are not redistributed.** Every one is downloaded by the
person using the app, from its own publisher. `NOTICE` says so, and says what
each one is, because reconstructing that list a year from now means opening
nine model cards.
"""
import re

from where import PKG


def _licence():
    return (PKG / "LICENSE").read_text(encoding="utf-8", errors="replace")


def _notice():
    return (PKG / "NOTICE").read_text(encoding="utf-8", errors="replace")


def test_there_is_a_licence_file():
    """With nothing stated, the default is all rights reserved -- which is
    the opposite of what lee said this was going to be."""
    assert (PKG / "LICENSE").is_file()


def test_it_is_the_real_gpl_and_not_a_summary_of_one():
    src = _licence()
    assert "GNU GENERAL PUBLIC LICENSE" in src
    assert "Version 3, 29 June 2007" in src
    # The operative sections rather than the preamble: a file holding only the
    # blurb grants nothing.
    for part in ("TERMS AND CONDITIONS", "Conveying Modified Source Versions",
                 "Disclaimer of Warranty"):
        assert part in src, part
    assert len(src) > 30000


def test_there_is_a_notice_file():
    assert (PKG / "NOTICE").is_file()


def test_the_notice_says_why_the_licence_is_this_one():
    """comic-text-detector is the reason, and it is not optional.

    Asked of the ENTRY rather than of the file: the name turning up somewhere
    in a paragraph proves nothing about whether the thing is listed.
    """
    src = _notice()
    assert re.search(r"^comic-text-detector$", src, re.M), \
        "the model that forces the licence has to be an entry of its own"
    assert "GPL-3.0" in src
    assert "not optional" in src


def test_every_model_the_code_can_load_is_listed():
    """A model somebody can point the app at and that nobody wrote down is
    exactly the one that causes trouble later."""
    src = _notice()
    for name in ("comictextdetector.pt.onnx", "detect-20241225.ckpt",
                 "dbpp_coo", "m109seg.pt", "animetext.pt", "detector.onnx",
                 "comic-speech-bubble-detector", "manga-ocr", "easyocr"):
        assert name in src, name


def test_each_entry_says_where_it_came_from():
    """A licence with no source to check it against is a rumour."""
    src = _notice()
    assert src.count("from      ") >= 8
    assert src.count("licence   ") >= 8


def test_the_notice_says_the_weights_are_not_redistributed():
    src = _notice()
    assert "NONE OF THE MODEL FILES ARE REDISTRIBUTED" in src.upper()
    assert "downloaded by the person using it" in src


def test_the_manga109_terms_are_written_down_rather_than_assumed():
    """Three of the models are trained on it and its terms are not a software
    licence. Whether they reach the weights is unsettled; the point is that
    the question is recorded."""
    src = _notice()
    assert re.search(r"^MANGA109, WHICH IS NOT A SOFTWARE LICENCE$", src,
                     re.M), "it needs a section, not a passing mention"
    assert "not settled" in src


def test_the_remote_engines_are_marked_as_out_of_scope():
    """The paid part. Services over HTTP are not code in this program."""
    src = _notice()
    assert "Anthropic" in src and "OpenAI" in src
    assert "services, not code" in src


def test_nobody_here_is_pretending_to_be_a_lawyer():
    assert "not legal advice" in _notice()


def test_the_notice_does_not_promise_licences_it_did_not_check():
    """Two of ogkalu's model cards stated nothing at the time of writing, and
    inventing an answer for them would be worse than saying so."""
    src = _notice()
    assert len(re.findall(r"check the model card", src)) >= 2
