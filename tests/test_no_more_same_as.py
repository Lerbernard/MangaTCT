"""The medium names the medium, and the boxes beside it hold answers.

lee: *"remove suport for comics and the project still supports mahnwa and
manhua, istad oaf saying manga- jappeneese ....., it shiud just fill the itehr
boxes wit default options, look thruought the project and remove all instandt of
smae as ... it shud just pre fill it with teh potion"*.

Three things, and they are the same thing:

* **Comic is gone.** Manga, manhwa, manhua. English survives as a source
  LANGUAGE — an already-translated scan being taken somewhere else still needs
  it — but not as a kind of book.
* **The option is the name.** "Manga", not "Manga — Japanese, reads right to
  left". The sentence in the option was doing the job of the two boxes next to
  it, which is why those two were allowed to sit there saying nothing.
* **Nothing says "same as".** "Same as the source material" and "Same as the
  project" are not answers to "Written in" and "Read text — the model that
  reads the page"; they are a promise that something else will answer later.
  Picking a medium now FILLS the other two with that medium's usual answers,
  where they can be seen and changed.

The values behind the old wording — `auto` in the two language boxes, `""` in a
per-step provider — still mean what they always meant when they are READ, so no
saved project changes behaviour. `Project.load` writes the resolved answer back
once, so the file stops saying `auto` too.
"""
import json
import re
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.project import Project
from mangatl.translate import MEDIA, source_language
from where import PKG

ROOT = PKG
HTML = (ROOT / "static" / "editor.html").read_text(encoding="utf-8")
IOJS = (ROOT / "static" / "js" / "project-io.js").read_text(encoding="utf-8")
PJS = (ROOT / "static" / "js" / "project.js").read_text(encoding="utf-8")


def _project(tmp_path, **settings):
    p = Project(None, str(tmp_path / "out"))
    p.add_uploaded("001.png", cv2.imencode(
        ".png", np.full((60, 40, 3), 255, np.uint8))[1].tobytes())
    p.save()
    if settings:
        d = json.loads(Path(p.state_path).read_text(encoding="utf-8"))
        for k in ("medium", "source", "direction"):
            d["settings"].pop(k, None)
        d["settings"].update(settings)
        Path(p.state_path).write_text(json.dumps(d), encoding="utf-8")
        p = Project(None, str(tmp_path / "out"))
    return p


# ------------------------------------------------------------- comic is gone

def test_the_three_media():
    assert set(MEDIA) == {"manga", "manhwa", "manhua"}


def test_english_is_still_a_source_language():
    """Dropping the medium must not drop the language: a scan already in
    English, being taken into Spanish, is an ordinary job."""
    assert source_language("manhwa", "en") == "English"


def test_the_screens_offer_exactly_the_three():
    for sel in ("pkMedium", "medium"):
        block = re.search(rf'id="{sel}".*?</select>', HTML, re.S).group(0)
        assert re.findall(r'<option value="(\w+)"', block) \
            == ["manga", "manhwa", "manhua"]


def test_the_option_is_the_name_and_nothing_else():
    """The dash and the sentence after it are what made the two boxes beside
    this one look like decoration."""
    for sel in ("pkMedium", "medium"):
        block = re.search(rf'id="{sel}".*?</select>', HTML, re.S).group(0)
        assert re.findall(r'>([^<]+)</option>', block) \
            == ["Manga", "Manhwa", "Manhua"]


# ------------------------------------------------------ nothing says "same as"

def test_no_screen_still_says_same_as():
    assert "Same as" not in HTML and "same as the" not in HTML


def test_the_language_boxes_have_no_automatic_answer():
    for sel in ("pkSource", "source", "pkDirection", "direction"):
        block = re.search(rf'id="{sel}".*?</select>', HTML, re.S).group(0)
        assert 'value="auto"' not in block, f"{sel} still offers auto"


def test_a_per_step_provider_is_a_provider():
    for step in ("ocr", "translate", "proofread"):
        block = re.search(rf'id="{step}_backend".*?</select>', HTML, re.S).group(0)
        assert 'value=""' not in block
    # ...and the box is FILLED from the STEP's own setting, inside the loop
    # that fills the three step rows. It used to be pre-filled from a
    # project-wide provider; that provider is gone, and a box that showed one
    # provider while the step called another is the disagreement these three
    # rows exist to end.
    loop = PJS.split("['ocr','translate','proofread'].forEach(k=>{")[1] \
              .split("\n  });")[0]
    assert "proj.settings[k+'_backend']" in loop, \
        "the step's provider box has to be filled from the step's own setting"
    assert "proj.settings.backend" not in loop, \
        "there is no project-wide provider to fall back to any more"


# --------------------------------------------------- picking one fills the rest

def test_the_screen_and_the_server_agree_on_what_a_medium_is():
    """The browser fills the two boxes; the server decides what the values
    mean. If those two ever disagree, the screen would say one thing and the
    pages would be read another way, silently."""
    table = re.search(r"const MEDIA=\{(.*?)\n\};", IOJS, re.S).group(1)
    js = {m: (src, d) for m, src, d in re.findall(
        r"(\w+):\s*\{source:'(\w+)',\s*direction:'(\w+)'\}", table)}
    assert js == {m: (v["code"], "rtl" if v["rtl"] else "ltr")
                  for m, v in MEDIA.items()}


def test_picking_a_medium_fills_both_boxes():
    body = IOJS.split("function mediumChosen(")[1].split("\n}")[0]
    assert "source" in body and "direction" in body
    for sel in ("pkMedium", "medium"):
        assert f'id="{sel}" onchange="mediumChosen(' in HTML


# ----------------------------------------------------- and no project changes

def test_a_new_project_answers_both_questions(tmp_path):
    p = _project(tmp_path)
    assert p.settings["source"] == "ja"
    assert p.settings["direction"] == "rtl"


def test_an_old_auto_project_is_written_out_as_what_it_meant(tmp_path):
    p = _project(tmp_path, medium="manhwa", source="auto", direction="auto")
    assert (p.settings["source"], p.settings["direction"]) == ("ko", "ltr")
    assert (p.source_code, p.rtl) == ("ko", False)


def test_an_old_project_that_named_neither_is_read_the_same_way(tmp_path):
    p = _project(tmp_path, medium="manhua")
    assert (p.source_code, p.rtl) == ("zh", False)


def test_an_old_comic_chapter_is_still_an_english_chapter(tmp_path):
    """This is the one that would have gone wrong quietly.

    Every reader of the setting does `MEDIA.get(medium, MEDIA["manga"])`, so a
    project saved as a comic would have come back Japanese and right-to-left the
    first time it was opened after the option was removed — the pages read in
    the wrong order and sent to a Japanese OCR engine. What the medium was
    ANSWERING for is pinned first; only the word for it moves.
    """
    p = _project(tmp_path, medium="comic")
    assert p.settings["medium"] == "manga"
    assert (p.source_code, p.rtl) == ("en", False)


def test_an_explicit_answer_survives_the_move(tmp_path):
    p = _project(tmp_path, medium="comic", source="es", direction="rtl")
    assert (p.source_code, p.rtl) == ("es", True)
