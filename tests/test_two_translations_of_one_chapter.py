"""`tools/mt_eval.py` - what separates two English versions of one chapter.

lee, after the reading was settled: *"now we move to translate text, i want
you to look only at any offline alternative to the ai traslator and evaluate
it against teh ai"*.

Reading a page of each and picking one is how you arrive at the answer you
started with, so the comparison got a tool. It counts the four things a
machine can see and a person then has to fix by hand:

    chrF          character agreement, per box kind. A SIMILARITY - two good
                  translations of one line disagree, and the number says so.
    names         one katakana run, how many English spellings. This is the
                  column the whole file was written for: the chapter's own
                  measurement put SIX names in two spellings each on the
                  offline side and none at all on the AI's, and that is the
                  difference between a glossary and no glossary.
    honorifics    -san / -sama kept where the Japanese has one.
    who           the person an English pronoun names where the Japanese
                  supplies none. Japanese drops the subject and English
                  cannot, so somebody decides - and one box is not enough to
                  decide from.

The tool imports nothing from the package (chrF is written out) so it runs
against two downloaded files on a bare Python, which is the shape of a thing
somebody actually uses.
"""
import json
import subprocess
import sys

import pytest

from where import PKG

TOOL = PKG / "tools" / "mt_eval.py"

# `tools/` is not a package and is not on the path - it is a folder of scripts
# somebody runs. The tool itself is exercised through the command line, the way
# it is used; these two lines are only so the three tests that check a single
# function can import it.
if str(TOOL.parent) not in sys.path:
    sys.path.insert(0, str(TOOL.parent))


def _chapter(rows):
    """rows: (page, id, kind, japanese, english)"""
    pages = {}
    for pg, i, kind, ja, en in rows:
        pages.setdefault(pg, []).append(
            dict(id=i, order=i, kind=kind, japanese=ja, english=en,
                 speaker=None))
    return {"pages": [{"name": k, "regions": v} for k, v in pages.items()]}


def _run(tmp_path, ref_rows, cand_rows):
    a, b = tmp_path / "ref.json", tmp_path / "cand.json"
    a.write_text(json.dumps(_chapter(ref_rows), ensure_ascii=False),
                 encoding="utf-8")
    b.write_text(json.dumps(_chapter(cand_rows), ensure_ascii=False),
                 encoding="utf-8")
    p = subprocess.run([sys.executable, str(TOOL), str(a), str(b)],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return p.stdout


# ------------------------------------------------------------------ chrF

def test_chrf_agrees_with_sacrebleu():
    """The one number here that somebody might check against a standard tool.

    Skipped where sacrebleu is not installed, which is most machines - the
    tool must not need it, which is the whole reason chrF is written out."""
    sb = pytest.importorskip("sacrebleu")
    from mt_eval import chrf
    h = ["Take a look.", "I get two copper Tarels back!", "Whoa! Scared me!"]
    r = ["Look closely.", "I get two copper Tarels back in change!",
         "Whoa! You startled me."]
    assert abs(chrf(h, r) - sb.corpus_chrf(h, [r]).score) < 0.01


def test_a_line_against_itself_is_a_hundred():
    from mt_eval import chrf
    assert chrf(["Ada, is something wrong?!"],
                ["Ada, is something wrong?!"]) > 99.9


def test_two_lines_with_nothing_in_common_are_near_nothing():
    from mt_eval import chrf
    assert chrf(["Zzz"], ["Ada"]) < 20


# ----------------------------------------------------------------- names

def test_one_name_spelled_two_ways_is_reported(tmp_path):
    """The chapter's real case: エーダ came back Eeda four times and Eda
    twice, from a translator with no glossary and no memory of page 4."""
    ref = [("001.jpg", 1, "bubble", "エーダ！", "Ada!"),
           ("002.jpg", 2, "bubble", "エーダさん", "Ada-san"),
           ("003.jpg", 3, "bubble", "エーダ…", "Ada...")]
    cand = [("001.jpg", 1, "bubble", "エーダ！", "Eeda!"),
            ("002.jpg", 2, "bubble", "エーダさん", "Eda-san"),
            ("003.jpg", 3, "bubble", "エーダ…", "Eeda...")]
    out = _run(tmp_path, ref, cand)
    assert "エーダ" in out
    assert "two spellings" in out
    assert "spells more than one way: 1" in out


def test_the_side_that_keeps_one_spelling_is_not_flagged(tmp_path):
    ref = [("001.jpg", 1, "bubble", "エーダ！", "Ada!"),
           ("002.jpg", 2, "bubble", "エーダ…", "Ada...")]
    out = _run(tmp_path, ref, ref)
    assert "spells more than one way: 0" in out


def test_a_vowel_is_a_vowel(tmp_path):
    """Ada and Eeda are one name written twice, and a table that files them
    as two different people has missed the only thing it is for."""
    from mt_eval import _romanish
    assert _romanish("Ada", "エーダ")
    assert _romanish("Eeda", "エーダ")
    assert _romanish("Glow", "グロウ") and _romanish("Gurou", "グロウ")


def test_the_word_that_merely_opens_a_sentence_is_not_a_name():
    """Without this the column fills with Right, Lady, These, and a name
    table nobody trusts is a name table nobody reads."""
    from mt_eval import _romanish
    for w in ("Right", "Lady", "These", "Let's", "Queen"):
        assert not _romanish(w, "ローファン") or not _romanish(w, "ターレル"), w
    assert not _romanish("Right", "ローファン")
    assert not _romanish("Let's", "ルージャ")


def test_a_name_seen_once_cannot_drift_and_is_left_out(tmp_path):
    out = _run(tmp_path,
               [("001.jpg", 1, "bubble", "トリオロン", "Trioron")],
               [("001.jpg", 1, "bubble", "トリオロン", "Torioron")])
    assert "トリオロン" not in out


# ------------------------------------------------------------ honorifics

def test_a_dropped_honorific_shows_on_both_lines(tmp_path):
    ref = [("001.jpg", 1, "bubble", "グロウさん!", "Glow-san!"),
           ("002.jpg", 2, "bubble", "レオノーラ様", "Leonora-sama")]
    cand = [("001.jpg", 1, "bubble", "グロウさん!", "Mr. Grow!"),
            ("002.jpg", 2, "bubble", "レオノーラ様", "Lady Leonora")]
    out = _run(tmp_path, ref, cand)
    assert "japanese lines with one   2" in out
    assert "kept by the reference     2" in out
    assert "kept by the candidate     0" in out


# ------------------------------------------------------------------- who

def test_it_only_asks_where_the_japanese_is_silent(tmp_path):
    """A line that says 私 has already answered the question, and counting it
    would bury the ones that matter."""
    from mt_eval import person
    assert person("I get two back") == {"1s"}
    assert person("You'll get two back") == {"2"}
    assert person("Let us see it") == {"1p"}
    assert person("Whoa!") == set()


def test_a_disagreement_about_who_is_shown_with_both_lines(tmp_path):
    """016's shopping sum: Ada is doing her own arithmetic out loud, and the
    box alone does not say so."""
    ref = [("016.jpg", 3, "bubble", "ターレル銅貨が二枚返ってきます",
            "I get two copper Tarels back in change!")]
    cand = [("016.jpg", 3, "bubble", "ターレル銅貨が二枚返ってきます",
             "You'll get two Tarrel copper coins back.")]
    out = _run(tmp_path, ref, cand)
    assert "and they disagree       1" in out
    assert "I get two copper Tarels" in out and "You'll get two" in out


def test_agreeing_about_who_says_nothing(tmp_path):
    ref = [("016.jpg", 3, "bubble", "二枚返ってきます", "I get two back.")]
    cand = [("016.jpg", 3, "bubble", "二枚返ってきます", "I'll get two back.")]
    assert "and they disagree       0" in _run(tmp_path, ref, cand)


# ------------------------------------------------------------- the shape

def test_sound_effects_are_counted_apart(tmp_path):
    """They came out a wash - 25 of 35 differed and most of the differences
    were taste, several of them in the offline reading's favour - so they get
    their own line rather than being averaged into the dialogue."""
    rows = [("001.jpg", 1, "bubble", "こんにちは", "Hello."),
            ("001.jpg", 2, "sfx", "ザッ", "STEP")]
    out = _run(tmp_path, rows, rows)
    assert "text" in out and "sfx" in out


def test_it_says_the_number_is_a_similarity_and_not_a_mark(tmp_path):
    """Somebody will read 56.7 as a percentage otherwise, and it is not one:
    two good translations of one line disagree."""
    rows = [("001.jpg", 1, "bubble", "こんにちは", "Hello.")]
    assert "not a mark" in _run(tmp_path, rows, rows)


def test_it_needs_nothing_from_the_package():
    """It runs on two downloaded files, on a bare Python, on his machine."""
    src = TOOL.read_text(encoding="utf-8")
    assert "from mangatl" not in src and "import mangatl" not in src


def test_it_prints_its_own_instructions_when_asked_for_nothing():
    p = subprocess.run([sys.executable, str(TOOL)],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 2
    assert "Download translations" in p.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
