"""The Read text step has two readers, and the person picks.

lee, after manga-ocr was measured against the AI on his chapter 3: *"add the
best as an option in the setting to choose between it or the ai"*.

Neither wins outright, which is why it is a menu and not a swap. Over 225
boxes the two agree on 83% of the dialogue; where they part it is usually the
AI that filed a line under the wrong box number (16 of 189, on 7 of 23 pages)
- a mistake reading one crop at a time cannot make. On painted sound effects
the AI wins and it is not close.

What is tested here is the WIRING, because that is where a second reader goes
wrong: a run that quietly still costs coins, a keyless machine refusing the
one reader that needs no key, or a reading path that skips the passes the
other one runs.
"""
import pytest

from mangatl import editor as E
from mangatl.project import Project
from where import PKG, JS, EDITOR_HTML


class _P:
    """Just enough project for the three wiring questions."""

    def __init__(self, **settings):
        self.settings = dict(settings)


def test_the_ai_is_the_default(tmp_path):
    p = Project(None, str(tmp_path))
    assert p.settings["ocr_reader"] == "ai"
    assert E.reading_offline(_P()) is False


def test_a_project_written_before_this_setting_existed_still_reads_with_ai():
    assert E.reading_offline(_P(medium="manga")) is False


def test_the_choice_is_one_function_everything_asks():
    assert E.reading_offline(_P(ocr_reader="offline")) is True
    assert E.reading_offline(_P(ocr_reader="OFFLINE")) is True
    assert E.reading_offline(_P(ocr_reader="ai")) is False


def test_reading_here_is_free():
    """The number on the button is what leaves the purse, and nothing leaves
    the machine, so nothing may leave the purse."""
    p = _P(ocr_reader="offline")
    assert E.run_price(p, "ocr", [0]) == (0, "", "")


def test_reading_here_asks_nobody_for_a_key():
    """Without this, the reader that exists for a keyless machine would be
    refused on one."""
    assert E.needs_key(_P(ocr_reader="offline"), "ocr") == ""


def test_the_other_steps_still_want_their_key():
    """Only the reading moved offline. Translate is still bought."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def needs_key("):]
    body = body[:body.index("\ndef ")]
    assert 'step == "ocr" and reading_offline(p)' in body, \
        "the exemption names the step it belongs to"


def test_the_price_check_comes_before_the_context_is_rewritten():
    """`step_engine` rewrites p.ctx from the AI settings. An offline read has
    no context to rewrite, and doing it anyway would hand the next paid step
    a context built for a run that never happened."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def run_price("):]
    body = body[:body.index("\ndef ")]
    assert body.index("reading_offline(p)") < body.index("step_engine(p, step)")


def test_both_readers_run_the_same_passes_after_the_words_arrive():
    """The relabel, the two drops, the sound that speaks, the links and the
    ink all ask questions about the WORDS. Words are words whoever read them,
    so they must sit AFTER the branch, not inside one arm of it."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def do_ocr("):]
    body = body[:body.index("\ndef ")]
    at = body.index("_read_with_ai(")
    for pass_name in ("symbol_only_boxes(regs)", "empty_boxes(regs)",
                      "link_sections(regs)", "measure_page(page"):
        assert body.index(pass_name) > at, pass_name


def test_reading_only_reads_and_takes_empty_boxes_away():
    """lee: *"make it so that read text only read teh etxt and not modify
    boxes exapt for removing boxes with no text or remoeving boxes with only
    symobos"*.

    Three passes that CHANGED a box came out with that sentence - a relabel
    from what was read in it, a sound effect demoted to speech, and a box
    whose reading was part of an overlapping box's. Each was measured and each
    worked; none of them was filling a box in, which is what this step is
    for."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def do_ocr("):]
    body = body[:body.index("\ndef ")]
    # The CALLS, not the words: the comment that replaced them names all
    # three, which is the point of it.
    # `read_twice_boxes` came back later - lee: *"can you gring teh fix we
    # had before"* - and it belongs: it REMOVES a box that holds no writing of
    # its own, which is the third of the removals the rule allows. The two
    # that RENAMED a box stayed out, and that is the line.
    for gone in ("speech_in_sfx(", "_relabel(", "from .readkinds import"):
        assert gone not in body, gone
    assert "read_twice_boxes(regs)" in body
    # ...and the whole module, not just this function
    assert "def speech_in_sfx" not in src
    # what may still go: nothing in it, or nothing but marks
    assert "symbol_only_boxes(regs)" in body and "empty_boxes(regs)" in body


def test_the_two_drops_still_happen_before_the_links():
    """A dropped box must never first be joined to its neighbour as the second
    half of a sentence - that leaves the line pointing at a box that is gone.
    """
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def do_ocr("):]
    body = body[:body.index("\ndef ")]
    assert (body.index("symbol_only_boxes(regs)")
            < body.index("link_sections(regs)"))
    assert body.index("empty_boxes(regs)") < body.index("link_sections(regs)")


def test_the_offline_read_goes_through_the_shared_engine_call():
    """`ocr.ocr_page` is what the command line has always called. One offline
    reading path, not two that drift apart."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def _read_here("):]
    body = body[:body.index("\ndef ")]
    assert "ocr_page(page" in body
    assert "get_engine(" in body, "the model is loaded before the count is said"


def test_the_offline_reader_is_handed_the_crop_at_its_own_size():
    """lee: *"use teh best mangaocr setting for the manga orc version"*. It
    was measured - 225 boxes at half, native and double, scored against the
    AI's crop-per-box read - and native won: CER 0.059 against 0.072 and
    0.062. It is also the size `prepare_crop` already makes, because the model
    resizes to 224px internally whatever it is given, so there is nothing to
    add and no second crop size to keep in step with the first."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def _read_here("):]
    body = body[:body.index("\ndef ")]
    assert "0.059" in body, "the measurement that chose the size is written down"
    # ...and the CODE, past the docstring, rescales nothing.
    code = body.split('"""', 2)[2]
    for word in ("resize", "glyph_px", "INTER_"):
        assert word not in code, f"the offline path must not rescale: {word}"


def test_a_locked_line_survives_a_re_read_by_either_reader():
    """The AI path has always kept this. The offline path shares the guard
    rather than repeating it, so it cannot be kept in one and not the other."""
    src = (PKG / "ocr.py").read_text(encoding="utf-8")
    body = src[src.index("def ocr_page("):]
    assert 'getattr(r, "locked", False)' in body
    assert 'getattr(r, "own_text", False)' in body


def test_auto_is_read_as_japanese_not_handed_to_the_engine():
    """Old projects have source "auto". `ocr.choose_engine` would fall
    through to easyocr on it, which is not what a Japanese page wants."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def _read_here("):]
    body = body[:body.index("\ndef ")]
    assert '"auto"' in body and 'lang = "ja"' in body


def test_the_choice_is_two_cards_on_the_settings_page():
    """lee: *"add a selecteabe tile for mangaorc and ai for the read text like
    teh find text"*, and then *"no add the setting in the setting page not in
    the popup"* / *"make teh cards in te setting look like teh find text
    ones"*. So: the detector routes' own card shape, in the detector routes'
    own section."""
    html = EDITOR_HTML.read_text(encoding="utf-8")
    at = html.index('id="readerCards"')
    block = html[at:html.index("</div>", html.index("offlineWhy"))]
    assert 'class="cards"' in html[at - 60:at + 60], \
        "the same grid the route cards use, not a variant of it"
    # ...in the settings section, ahead of the detector cards it matches
    body = html[html.index('<section class="set-section" data-sec="detection">'):]
    body = body[:body.index("</section>")]
    assert 'id="readerCards"' in body
    assert body.index('id="readerCards"') < body.index('id="routeCards"')
    assert 'data-reader="ai"' in block
    assert 'data-reader="offline"' in block
    assert "pickReader('ai')" in block and "pickReader('offline')" in block
    # ...and honest about what each one loses
    assert "painted sounds" in block     # the AI is the one that reads them
    assert "painted sound." in block     # ...and the offline one invents them
    assert "wrong box" in block          # while never filing under the wrong one


def test_the_old_menu_is_gone_and_so_is_reading_detail():
    html = EDITOR_HTML.read_text(encoding="utf-8")
    assert 'id="ocr_reader"' not in html, "the select it replaced"
    assert 'id="ocr_detail"' not in html, "not a choice any more at all"
    js = (JS / "project.js").read_text(encoding="utf-8")
    assert "function syncReader()" not in js


def test_the_cards_are_lit_and_saved_from_the_settings_module():
    """They are a settings control, so they live beside the other settings
    controls rather than in the run dialog's module."""
    js = (JS / "project.js").read_text(encoding="utf-8")
    assert "function syncReaderCards()" in js
    assert "function pickReader(" in js
    body = js.split("function pickReader(", 1)[1].split("\nfunction ", 1)[0]
    assert "saveSettings()" in body
    assert "syncReaderCards()" in body
    # ...and the loader lights the right one when a project opens
    assert js.index("syncReaderCards()") < js.index("function syncReaderCards()")
    pipe = (JS / "pipeline.js").read_text(encoding="utf-8")
    assert "syncReaderCards" not in pipe


def test_reading_here_puts_no_number_on_the_button():
    """Not "0", and not "free" either - lee: *"instaead of sayong free it
    shoud show nothiing"*. The same silence every other free step gets."""
    js = (JS / "pipeline.js").read_text(encoding="utf-8")
    body = js.split("function priceScope(", 1)[1].split("\nfunction ", 1)[0]
    at = body.index("ocr_reader")
    assert "put(all, null); put(one, null); return;" in body[at:at + 200]
    assert "'free'" not in body and '"free"' not in body


def test_the_offline_card_is_named_for_the_language_it_would_use():
    """"On this computer" is a different program per language - manga-ocr
    reads Japanese and nothing else, easyocr is a general engine having a go
    at comics. One name for both would be wrong on one of them."""
    js = (JS / "project.js").read_text(encoding="utf-8")
    body = js.split("function syncReaderCards(", 1)[1].split("\nfunction ", 1)[0]
    assert "manga-ocr" in body and "easyocr" in body
    assert "proj.settings.source" in body


def test_the_choice_is_still_saved_with_the_project():
    js = (JS / "project.js").read_text(encoding="utf-8")
    assert "ocr_reader:(proj.settings.ocr_reader||'ai')" in js, \
        "carried through the sheet even though nothing on that screen edits it"


# ------------------------------------------- and the crop is not padded either

def _read_here_doc() -> str:
    return E._read_here.__doc__ or ""


def test_the_margin_sweep_is_written_down_where_the_crop_is_decided():
    """lee: *"add the 10% for ecerything not just sfx aand test it"*, after one
    sound effect was fixed by a tenth of a box's width.

    It was tested and it is not an improvement, which is a result that has to
    be RECORDED or it gets re-proposed the next time somebody notices that same
    one box. So the table lives on the function that decides the crop, beside
    the size measurement it belongs with."""
    doc = _read_here_doc()
    assert "NOT PADDED" in doc
    for margin in ("0%", "5%", "10%", "15%", "20%", "30%"):
        assert margin in doc, margin


def test_it_says_why_the_big_margins_are_worse_and_not_only_that_they_are():
    """A number with no mechanism is a number somebody explains away. The
    mechanism is in the readings: past fifteen per cent the neighbouring
    balloon is inside the crop and gets read as part of the line."""
    doc = _read_here_doc()
    assert "neighbouring balloon" in doc
    assert "read as part of the line" in doc


def test_the_ten_per_cent_result_is_stated_as_a_wash_not_as_a_win():
    """0.076 against 0.078 over 32 lines is one box each way. Writing that up
    as an improvement is how a constant nobody can justify gets into the
    code."""
    doc = _read_here_doc()
    assert "not an improvement" in doc
    assert "one box\n    gained" in doc and "one lost" in doc


def test_and_nothing_in_the_reading_path_actually_pads():
    """The docstring is the argument; this is the code agreeing with it."""
    src = (PKG / "ocr.py").read_text(encoding="utf-8")
    body = src[src.index("def prepare_crop("):]
    body = body[:body.index("\ndef ")]
    for word in ("margin", "PAD_SHARE", "pad_share"):
        assert word not in body, word


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
