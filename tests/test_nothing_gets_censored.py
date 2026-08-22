"""Nothing on the page gets censored that the page did not censor itself.

lee: *"make sure that ther is not censoreing of any word at all"*, and then the
one exception: *"unless it it cenored inth emnga itself you can add * if the
managa itselft has it"*.

Softening a swear is a mistranslation. The author decided how hard that line
lands, and a translator who letters "f***" where the Japanese says the word
outright has edited the book. Mirroring a mask the page DOES carry is the
opposite - that mask is part of what the page says, and it has to survive the
trip through the typesetter intact.

Two halves, because neither is enough alone:

* **The prompt says so.** Both the translator's and the proofreader's briefs
  now carry the rule in as many words, including the one exception.
* **The code notices.** `added_masking` compares the line against its source:
  a mask in the English with no mask behind it in the original is the model
  censoring on its own account, and the region is flagged so lee sees it.

It only reports. Nothing can put a word back once the model has thrown it away,
and a page that fails outright is worse than a page with one line to check -
lee: *"ill ratter have it do a bad job then not do it at all"*.
"""
from types import SimpleNamespace

import numpy as np
import pytest

from mangatl.translate import (CENSOR_NOTE, SeriesContext, added_masking,
                               build_proofread_system, build_system,
                               translate_page)


# --------------------------------------------------------- what counts as one

@pytest.mark.parametrize("dst,src", [
    ("f***", "くそったれ"),
    ("sh*t", "クソ"),
    ("f#@!", "クソが"),                  # a grawlix is masking too
    ("What the h***?", "何だと"),
    ("GET B*CK HERE", "戻れ"),
])
def test_masking_the_page_never_asked_for(dst, src):
    assert added_masking(dst, src)


@pytest.mark.parametrize("dst,src", [
    ("f***", "＊＊＊"),                   # the page masks its own word...
    ("f***", "〇〇〇"),
    ("SH*T", "×××"),
    ("Shit", "クソ"),                    # ...or the word is simply said
    ("Fuck off", "失せろ"),
])
def test_what_is_not_the_model_censoring_itself(dst, src):
    assert not added_masking(dst, src)


@pytest.mark.parametrize("dst", ["WOW!!", "5 * 4 = 20", "100%", "Mr. A",
                                 "TURN", "", "Wait—no"])
def test_ordinary_typesetting_is_not_mistaken_for_a_mask(dst):
    """A shout, a sum and a percentage all carry these characters and none of
    them is a masked word. Both halves of the test matter: a warning raised
    about a page that did nothing wrong is worse than none at all."""
    assert not added_masking(dst, "何か")


# ------------------------------------------------------------ what the AI is told

@pytest.mark.parametrize("brief", [build_system, build_proofread_system])
def test_both_briefs_forbid_it(brief):
    text = brief("manga", "en").lower()
    assert "never censor" in text
    assert "mask" in text


def test_the_brief_still_allows_the_page_its_own_mask():
    text = build_system("manga", "en").lower()
    assert "mirror" in text and "own" in text


# ------------------------------------------------------------- the whole way in

def _page(src):
    from mangatl.models import Page, TextRegion
    p = Page(image=np.full((100, 100, 3), 255, np.uint8))
    p.regions = [TextRegion(id=0, bbox=(0, 0, 40, 20), src_text=src)]
    return p


def _client(translation):
    reply = ('{"regions":[{"id":0,"translation":"%s","confidence":0.9}],'
             '"page_notes":"","glossary_additions":{}}' % translation)
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw:
        SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])))


def test_a_self_censored_line_comes_back_flagged():
    page = _page("くそったれ")
    translate_page(page, SeriesContext(), client=_client("f***"))
    r = page.regions[0]
    assert CENSOR_NOTE in (r.flagged or ""), \
        "the model masked a word the page does not mask, and said nothing"


def test_the_masked_line_itself_is_left_alone():
    """Flagged, not mangled. There is no way to guess the word back, and
    typesetting "f" would be worse than typesetting "f***"."""
    page = _page("くそったれ")
    translate_page(page, SeriesContext(), client=_client("f***"))
    assert page.regions[0].dst_text == "f***"


def test_a_mask_the_page_carries_is_not_a_complaint():
    page = _page("〇〇〇め")
    translate_page(page, SeriesContext(), client=_client("f***"))
    r = page.regions[0]
    assert r.dst_text == "f***"
    assert CENSOR_NOTE not in (r.flagged or "")


def test_the_copy_editor_is_watched_too():
    """The proofreader gets the line AFTER it has been translated, and is just
    as able to reach for a mask on the way past."""
    from mangatl.models import Page, TextRegion
    from mangatl.translate import proofread_page

    page = Page(image=np.full((100, 100, 3), 255, np.uint8))
    page.regions = [
        TextRegion(id=0, bbox=(0, 0, 10, 10), src_text="くそったれ",
                   dst_text="Fuck off."),
        TextRegion(id=1, bbox=(0, 20, 10, 10), src_text="そうだ",
                   dst_text="That's it!"),
    ]
    reply = ('{"regions":[{"id":0,"text":"F*** off."},'
             '{"id":1,"text":"That\'s it!"}],"page_notes":""}')
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw:
        SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])))

    proofread_page(page, SeriesContext(), client=fake)

    assert page.regions[0].dst_text == "F*** off."
    assert CENSOR_NOTE in (page.regions[0].flagged or "")
    assert CENSOR_NOTE not in (page.regions[1].flagged or "")


def test_a_line_that_swears_outright_passes_without_comment():
    page = _page("くそったれ")
    translate_page(page, SeriesContext(), client=_client("Fuck off."))
    r = page.regions[0]
    assert r.dst_text == "Fuck off."
    assert CENSOR_NOTE not in (r.flagged or "")
