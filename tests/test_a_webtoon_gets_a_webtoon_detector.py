"""Four cards on a strip, and not the four that were measured on a manga.

lee: *"ok now i want tyou to test a bunch of box finders and add the goods
ones as coard for mahhwa and manhua and add ctd as one"*, *"4 in total"*, and
the sentence that decided which four: *"we to find and use detector that are
good for manwa and mnahua not the same ones at teh manga"*.

Seven finders were run on 22 tiles of lee's own Korean chapter. Manga109
found nothing at all on a webtoon; DB++/COO found nothing; CRAFT answers
character groups rather than blocks; comic-translate's 8k model drew loose
overlapping boxes at 16-23s. What was left is these four, hand-checked
against the 33 balloons and captions on the chapter:

    route                 missed  junk  s/page
    comic-text-detector        1     2     2.8
    Webtoon balloons KO        1     0     2.8
    Webtoon balloons ZH        5     1     2.8
    AnimeText YOLO12-L         1     3     4.7

The things that can go quietly wrong here, which is what this file is for:

* **A card offered on a format its route refuses to run on.** Every guard is
  written down three times - `why_not_*` on the server, `route_media` beside
  it, `ROUTE_MEDIA` in the browser - and three copies of a rule is three
  chances for one of them to say something else.
* **A default that is set and cannot run.** `webtoon_ko` ships ON so that a
  strip gets a webtoon default with no per-format defaults table. That means
  on a manga the flag is set and the route is guarded off, and anything that
  reads the flag alone - the card that lights up, the model that is warmed,
  the route named in a slow-page line - would be wrong.
* **A save on one format quietly deciding the other.** The settings page
  sends every route key on every save, so a card picked on a manga must not
  turn the webtoon default off for the manhwa in the same project.
"""
import tempfile

import numpy as np
import pytest

from where import PKG, EDITOR_HTML, JS, CSS

from mangatl.models import Page, TextRegion
from mangatl.detect import webtoon as WT
from mangatl.project import Project, STRIP_MEDIA


def _p(**settings):
    p = Project(None, tempfile.mkdtemp())
    p.settings.setdefault("medium", "manhwa")
    p.settings.update(settings)
    return p


# ----------------------------------------------------- which card, which format

def test_the_webtoon_pair_is_offered_on_a_strip_and_nowhere_else():
    """A manga has no use for them and they were never measured on one."""
    for m in ("manhwa", "manhua"):
        p = _p(medium=m)
        assert p.route_here("webtoon_ko") and p.route_here("webtoon_zh")
        assert not p.why_not_webtoon_ko().startswith("this route")
    p = _p(medium="manga")
    assert not p.route_here("webtoon_ko")
    assert "manhua and manhwa" in p.why_not_webtoon_ko()


def test_the_two_that_need_panels_are_not_offered_on_a_strip():
    """`TWO_MEDIA` is a guard on numbers swept on manga fragments, and a
    manhwa is one tall column with no panels across it."""
    p = _p(medium="manhwa")
    for key in ("two_specialists", "manga_segmenter"):
        assert not p.route_here(key), key
    assert p.route_here("animetext"), "AnimeText was counted on a webtoon too"


def test_the_browser_and_the_server_offer_the_same_four():
    """Three copies of one rule. The card group is what somebody clicks, the
    `why_not_*` guards are what actually runs, and a card on screen whose
    route refuses is a card that silently does nothing."""
    js = JS.joinpath("project.js").read_text(encoding="utf-8")
    block = js[js.index("const ROUTE_MEDIA"):js.index("const ROUTES")]
    for key in ("webtoon_ko", "webtoon_zh"):
        line = block[block.index(key):]
        line = line[:line.index("\n")]
        assert "manhwa" in line and "manhua" in line and "manga'" not in line
    for key in ("two_specialists", "manga_segmenter"):
        line = block[block.index(key):]
        line = line[:line.index("\n")]
        assert "manhwa" not in line and "manhua" not in line, key
    line = block[block.index("animetext"):]
    line = line[:line.index("\n")]
    assert "manga" in line and "manhwa" in line and "manhua" in line


def test_a_card_this_format_does_not_offer_actually_leaves_the_screen():
    """It did not, the first time, and it was on screen that it showed: all
    six cards at once on a manhwa, with DB++/COO and Manga109 sitting there
    blank because `rateRoutes` has no webtoon count to put on them.

    The cause is one line of CSS beating one line of JS. `c.hidden = true`
    relies on the browser's own `[hidden]{display:none}`, which is a
    UA-stylesheet rule and loses to ANY author rule that sets display - and
    `.cards .card{display:flex}` is exactly that. So the attribute was set,
    correctly, on cards that stayed visible.

    Both halves are asserted here, because either one alone reads as
    arbitrary: the stylesheet DOES set display on these cards, and the code
    therefore hides them with `style.display` rather than the attribute."""
    css = CSS.joinpath("editor.css").read_text(encoding="utf-8")
    assert ".cards .card{display:flex" in css
    js = JS.joinpath("project.js").read_text(encoding="utf-8")
    body = js[js.index("function syncRoutes("):js.index("function rateRoutes(")]
    assert "c.style.display = here ? '' : 'none';" in body
    assert "c.hidden" not in body, "the attribute cannot beat that CSS rule"


def test_every_offered_card_is_in_the_markup_and_the_picker():
    html = EDITOR_HTML.read_text(encoding="utf-8")
    js = JS.joinpath("project.js").read_text(encoding="utf-8")
    for key in ("webtoon_ko", "webtoon_zh"):
        assert 'data-route="%s"' % key in html
        assert "'%s'" % key in js


def test_a_card_shown_on_a_strip_carries_the_numbers_counted_on_one():
    """`data-sec` is 23 pages of Japanese manga and `data-wsec` is lee's
    Korean chapter, and the card picks by the format on screen. One number
    shown on both formats would be wrong half the time it was read."""
    html = EDITOR_HTML.read_text(encoding="utf-8")
    for key in ("webtoon_ko", "webtoon_zh"):
        card = html[html.index('data-route="%s"' % key):]
        card = card[:card.index("</button>")]
        assert "data-wsec=" in card and "data-wmissed=" in card
        assert "data-sec=" not in card, "never measured on a manga"
    for key in ('data-route=""', 'data-route="animetext"'):
        card = html[html.index(key):]
        card = card[:card.index("</button>")]
        assert "data-sec=" in card and "data-wsec=" in card, key
    js = JS.joinpath("project.js").read_text(encoding="utf-8")
    assert "const WEBTOON_SITES = 33;" in js


# ---------------------------------------------- the default that ships set on

def test_the_strip_default_is_a_webtoon_model_and_the_manga_one_is_not():
    """One static flag doing a per-format default. On a manga `webtoon_ko` is
    set and guarded off, so the route that runs is AnimeText; on a manhwa it
    is asked first and wins."""
    assert _p().settings.get("webtoon_ko") is True
    assert _p().settings.get("animetext") is True


def test_a_flag_that_is_set_but_guarded_off_is_not_the_route(monkeypatch):
    """`route_key` asks each route's own predicate, not the flag. Reading the
    flags alone is how a manga would name a webtoon route it cannot run, warm
    a 12MB model nothing will call, and light the wrong card."""
    p = _p(medium="manga")
    monkeypatch.setattr(Project, "animetext", lambda self: True)
    monkeypatch.setattr(Project, "webtoon_ko", lambda self: False)
    assert p.route_key() == "animetext"
    assert p.route_name() == "AnimeText YOLO12-L"


def test_on_a_strip_the_webtoon_model_is_asked_first(monkeypatch):
    p = _p(medium="manhwa")
    monkeypatch.setattr(Project, "animetext", lambda self: True)
    monkeypatch.setattr(Project, "webtoon_ko", lambda self: True)
    assert p.route_key() == "webtoon_ko"


def test_a_route_whose_checkpoint_is_missing_is_not_the_route(tmp_path,
                                                              monkeypatch):
    """The name has to be the one that RAN. `_detect_measured` falls through
    when the weights are not there, so a `route_key` that stopped at the flag
    would put a route nobody used in the slow-page line."""
    from mangatl import project as P
    monkeypatch.setattr(P, "__file__", str(tmp_path / "project.py"))
    p = _p(medium="manhwa")
    assert p.route_key() == ""
    assert p.route_name() == "comic-text-detector"


def test_the_dialog_says_why_a_card_is_grey_rather_than_hiding_it():
    """`partly` is what puts a disabled card on screen with a reason in it.
    False on a manga on purpose: a format the route was never measured on
    should not be shown a switch at all."""
    on = _p(medium="manhwa").summary()["webtoon_ko"]
    off = _p(medium="manga").summary()["webtoon_ko"]
    assert on["partly"] is True and off["partly"] is False
    assert _p(medium="manhwa").summary()["animetext"]["partly"] is True
    assert _p(medium="manhwa").summary()["two_specialists"]["partly"] is False


def test_a_save_on_one_format_leaves_the_other_formats_answer_alone():
    """`routeFlag` passes an unoffered route through untouched. Turning them
    off would mean picking Manga109 on a manga quietly took the webtoon
    default off the manhwa in the same project."""
    js = JS.joinpath("project.js").read_text(encoding="utf-8")
    for key in ("webtoon_ko", "webtoon_zh", "two_specialists",
                "manga_segmenter", "animetext"):
        assert "%s:routeFlag('%s')" % (key, key) in js, key
    fn = js[js.index("function routeFlag"):]
    fn = fn[:fn.index("\n}")]
    assert "routeHere(k)" in fn and "proj.settings[k]" in fn


def test_the_route_is_asked_before_animetext():
    """It falls through when the weights are absent, so it has to be first or
    AnimeText answers on a strip and the webtoon models never get a turn."""
    src = (PKG / "project.py").read_text(encoding="utf-8")
    body = src[src.index("def _detect_measured"):]
    assert body.index("self.webtoon_ko()") < body.index("self.animetext()")


def test_the_sound_effect_model_is_not_warmed_for_a_route_that_ignores_it():
    """COO is the 116MB one and the slowest to load. `detect_webtoon` takes
    `want_sfx` and ignores it - these models answer balloon or not-balloon -
    so a webtoon route that paid fifteen seconds to load it would be paying
    for nothing, in the moment this whole method exists to make cheap."""
    src = (PKG / "project.py").read_text(encoding="utf-8")
    body = src[src.index("def warm_models"):]
    body = body[:body.index("\n    #: Where comic-text-detector")]
    assert 'if key in ("webtoon_ko", "webtoon_zh"):' in body
    assert body.index('if key in ("webtoon_ko"') < body.index("elif key:")


# ------------------------------------------------------------- what it finds

def test_one_box_per_piece_of_writing_however_often_it_was_found():
    """The page is read in overlapping tiles, so a balloon found whole in two
    of them can survive the non-maximum pass, and a model willing to call
    both a caption and most of a caption a balloon does the same inside one
    tile. lee's page 47 came back with a three-line caption as two rectangles
    offset diagonally, neither inside the other.

    They are JOINED and not one dropped: neither box there held all three
    lines and their union does, so dropping either would have cut a line off
    the translation."""
    def r(x, y, w, h):
        t = TextRegion(id=0, bbox=(x, y, w, h), kind="bubble",
                       text_mask=np.zeros((300, 300), np.uint8))
        t.text_mask[y:y + h, x:x + w] = 255
        return t
    got = WT._one_box_per_writing([r(10, 10, 100, 60), r(30, 30, 100, 60)])
    assert len(got) == 1
    assert tuple(got[0].bbox) == (10, 10, 120, 80), "the union, not either one"
    assert got[0].text_mask[35, 115] == 255, "and the ink of both"
    # ...and two balloons that merely touch are two balloons.
    got = WT._one_box_per_writing([r(10, 10, 100, 60), r(105, 10, 100, 60)])
    assert len(got) == 2


def test_the_box_reaches_writing_the_balloon_box_left_outside_it():
    """A caption plate that steps in behind a neighbour gets a rectangle
    round the part of the plate the model can see, and on lee's page 47 that
    stopped nine pixels above the third line of three. A translation of the
    first two lines is a wrong translation, not a short one.

    The mask may push the corners OUT and never in - it is patchy on colour
    art, which is the whole reason these models are here."""
    mask = np.zeros((300, 300), np.uint8)
    mask[20:40, 20:120] = 255          # line one, inside the box
    mask[45:65, 20:120] = 255          # line two, just below it
    r = TextRegion(id=0, bbox=(15, 15, 110, 30), kind="bubble",
                   text_mask=mask.copy())
    got = WT._reach_the_last_line([r], mask)[0]
    x, y, w, h = got.bbox
    assert y + h >= 65, "the second line is inside the box now"
    assert got.text_mask[50, 60] == 255, "and the cleaner is told to erase it"


def test_writing_another_box_already_holds_is_not_adopted():
    """Two captions stacked touching, and the second's first line is nine
    pixels from the first's last one. What keeps them apart is that a line
    already inside somebody else's box is not up for adoption."""
    mask = np.zeros((300, 300), np.uint8)
    mask[20:40, 20:120] = 255          # caption one
    mask[50:70, 20:120] = 255          # caption two, a hair below
    a = TextRegion(id=0, bbox=(15, 15, 110, 30), kind="bubble",
                   text_mask=mask.copy())
    b = TextRegion(id=1, bbox=(15, 45, 110, 30), kind="bubble",
                   text_mask=mask.copy())
    got = WT._reach_the_last_line([a, b], mask)
    assert len(got) == 2
    assert tuple(got[0].bbox) == (15, 15, 110, 30), "left where it was"


def test_the_line_the_box_cuts_through_is_taken_in():
    """lee, two screenshots of caption plates with the first line half in the
    box and half out - `나는……` on 022, `지금까지` on 007. The artist set the
    line across the plate's top rule; the model boxed the plate; and the
    rule that grows boxes over writing called the line "somebody's already
    reading it" because the box touched it. Two lines of three went to the
    reader."""
    mask = np.zeros((300, 300), np.uint8)
    mask[10:34, 40:130] = 255           # line one: 24 tall, box top at 20
    mask[45:65, 40:130] = 255           # line two, inside
    r = TextRegion(id=0, bbox=(30, 20, 110, 60), kind="bubble",
                   text_mask=mask.copy())
    got = WT._reach_the_last_line([r], mask)[0]
    x, y, w, h = got.bbox
    assert y <= 10, "the box now starts above the first line"
    assert got.text_mask[12, 80] == 255, "and the cleaner is told about it"


def test_a_shape_crossing_the_box_edge_does_not_move_it():
    """Colour art: the mask marks the odd piece of drawing, and a piece of
    drawing crossing the box edge must not drag the box out over it. Taller
    than the box is a shape; one box's line is never that."""
    mask = np.zeros((300, 300), np.uint8)
    mask[0:150, 100:120] = 255          # a vertical stroke down through the box
    r = TextRegion(id=0, bbox=(30, 20, 110, 60), kind="bubble",
                   text_mask=mask.copy())
    got = WT._reach_the_last_line([r], mask)[0]
    assert tuple(got.bbox) == (30, 20, 110, 60)
    # ...and a mark that two boxes touch is between two captions: neither
    # moves onto it.
    mask = np.zeros((300, 300), np.uint8)
    mask[38:52, 40:130] = 255           # a line lying across both edges
    a = TextRegion(id=0, bbox=(30, 10, 110, 30), kind="bubble")
    b = TextRegion(id=1, bbox=(30, 45, 110, 30), kind="bubble")
    got = WT._reach_the_last_line([a, b], mask)
    assert tuple(got[0].bbox) == (30, 10, 110, 30)
    assert tuple(got[1].bbox) == (30, 45, 110, 30)
    assert 0.1 <= WT.STRADDLE <= 0.5


def test_the_mask_is_page_sized_and_not_a_crop():
    """`TextRegion.place_mask` reads `text_mask.shape` as the page's shape and
    `balloon` compares it against page-sized label images. A cropped mask does
    not fail a check - it raises a broadcast error four calls away from here,
    which is how this was found."""
    src = (PKG / "detect" / "webtoon.py").read_text(encoding="utf-8")
    assert "ink = np.zeros(tmask.shape[:2], np.uint8)" in src


def test_a_balloon_drawn_empty_is_not_a_box():
    """`MIN_INK` as a share of the balloon's own area. A bubble somebody drew
    with nothing in it has nothing to translate."""
    assert 0 < WT.MIN_INK < 0.01


def test_it_says_what_to_do_rather_than_raising(tmp_path):
    assert "no webtoon detector weights are set" == WT.why_not("")
    assert str(tmp_path / "no.onnx") in WT.why_not(str(tmp_path / "no.onnx"))


@pytest.mark.parametrize("medium", sorted(STRIP_MEDIA))
def test_the_sound_effect_tick_is_answered(medium):
    """It used to be accepted and ignored, honestly and uselessly: these
    models answer balloon or not-balloon. lee, having watched them find none
    of the six painted sounds on ten pages of his own chapter: *"i wnat you
    to test teh 4 detector ... adn have teh finded evrything including the
    big sfx"*. So the tick is passed to the model underneath them, which can."""
    src = (PKG / "detect" / "webtoon.py").read_text(encoding="utf-8")
    assert "want_sfx=want_sfx" in src
    assert medium in STRIP_MEDIA


# ------------------------------------------- what the balloon model cannot do

def _r(x, y, w, h, kind="bubble"):
    return TextRegion(id=0, bbox=(x, y, w, h), kind=kind)


def test_a_box_the_balloon_model_already_has_is_not_added_twice():
    """A balloon the webtoon model found is the webtoon model's - it is
    better at them, which is the whole reason this route exists. Two boxes on
    one balloon is two translations of one line, and the union of a tight box
    and a loose one is the loose one."""
    got = [_r(100, 100, 200, 100)]
    WT._fill_in(got, [_r(120, 110, 150, 70, "bubble")], "all")
    assert len(got) == 1
    assert tuple(got[0].bbox) == (100, 100, 200, 100), "the tight one stayed"


def test_a_box_drawn_round_a_CLUSTER_of_balloons_is_not_added_either():
    """lee, over a screenshot of two balloons inside a third box: *"the big
    box should not hapen"*.

    The direction that was wrong. The share was taken of the INCOMING box's
    own area, which settles a small box landing inside a big balloon and gets
    this exactly backwards: comic-text-detector draws one block round a
    CLUSTER of balloons, that block shares only a little of its own large area
    with any one of them, so it passed the test and went in - a box round two
    balloons that already had boxes, on top of them both.

    Asking about the SMALLER of the two answers both directions at once."""
    got = [_r(100, 100, 200, 90), _r(110, 210, 260, 120)]
    n = WT._fill_in(got, [_r(80, 80, 320, 280, "bubble")], "all")
    assert n == 0, "the block round both of them"
    assert len(got) == 2

    # ...and it is still dropped when it holds only ONE of them, because the
    # balloon model's box is the better box either way.
    got = [_r(100, 100, 200, 90)]
    assert WT._fill_in(got, [_r(80, 80, 260, 140, "bubble")], "all") == 0
    assert len(got) == 1


def test_a_sound_effect_that_ran_into_a_balloon_is_cut_back_not_dropped():
    """227's page 13: `우아악!` painted the height of the panel, and the box
    the sound-effect pass grew round it took in the balloon above. It covered
    a balloon, so it was dropped, and the biggest sound on the page came off
    the run with nothing on it. Page 14's `질` went the same way.

    Now the balloon is cut out of it and the biggest strip left stays - here
    the bottom two thirds, which is where the sound is."""
    balloon = _r(191, 1430, 248, 102)
    got = [balloon]
    n = WT._fill_in(got, [_r(0, 1316, 355, 674, "sfx")], "all")
    assert n == 1 and len(got) == 2
    sfx = [r for r in got if r.kind == "sfx"][0]
    assert tuple(sfx.bbox) == (0, 1532, 355, 458), "the strip under the balloon"
    assert tuple(sfx.bubble_bbox) == tuple(sfx.bbox)
    assert not WT._covers(sfx.bbox, balloon.bbox), "and it is off the balloon"


def test_the_cut_takes_the_ink_mask_and_the_outline_with_it():
    """The box is not the only thing that says where a region is. The cleaner
    reads `text_mask`; a mask that still holds the balloon's ink after the box
    has left it erases the balloon."""
    m = np.zeros((2000, 400), np.uint8)
    m[1320:1980, 10:340] = 255
    r = TextRegion(id=0, bbox=(0, 1316, 355, 674), kind="sfx", text_mask=m)
    r.polygon = [[0, 1316], [355, 1316], [355, 1990], [0, 1990]]
    got = [_r(191, 1430, 248, 102)]
    WT._fill_in(got, [r], "all")
    assert r.text_mask.shape == (2000, 400), "still page-sized"
    assert r.text_mask[1400, 200] == 0, "the balloon's part is gone"
    assert r.text_mask[1600, 200] == 255, "the sound's part is not"
    assert r.polygon == [[0, 1532], [355, 1532], [355, 1990], [0, 1990]]


def test_a_box_that_is_mostly_balloon_still_goes():
    """The two cases the old rule was written for come out under the line:
    a box inside a balloon has no strip worth the name, and a block round a
    cluster loses too much with every balloon cut out of it. Measured against
    the box AS IT CAME IN, so a block round three balloons cannot survive by
    shedding them one at a time."""
    assert WT._clear_of_the_balloons((120, 110, 150, 70),
                                     [(100, 100, 200, 100)]) is None
    # 60% strip survives one balloon; the second cut takes it under 40%
    assert WT._clear_of_the_balloons((80, 80, 320, 280),
                                     [(100, 100, 200, 90)]) == (80, 190, 320, 170)
    assert WT._clear_of_the_balloons(
        (80, 80, 320, 280), [(100, 100, 200, 90), (110, 210, 260, 120)]) is None
    # a box that does not cover any balloon is left exactly as it was
    assert WT._clear_of_the_balloons((400, 900, 180, 90),
                                     [(100, 100, 200, 100)]) == (400, 900, 180, 90)
    assert 0.3 <= WT.CARVE_KEEP <= 0.5


def test_craft_is_told_what_a_painted_sound_looks_like_on_this_route():
    """Task #144. Two CRAFT numbers set on printed manga type were costing
    the painted sounds: `low_text` 0.50 broke a gradient stroke into crumbs,
    and `craft_cap` 0.05 threw away a shout that was a twentieth of a strip.
    Swept on 66 sounds over two chapters; 0.30 / 0.45 took lee's chapter
    from 41% to 64% of sounds nine-tenths covered. Held here so a later
    manga measurement cannot quietly move them back."""
    assert WT.CRAFT_LOW == 0.30
    assert WT.CRAFT_CAP == 0.45
    src = (PKG / "detect" / "webtoon.py").read_text(encoding="utf-8")
    body = src[src.index("def detect_webtoon("):src.index("def _fill_in(")]
    assert 'quiet["craft_low"] = CRAFT_LOW' in body
    assert 'quiet["craft_cap"] = CRAFT_CAP' in body
    # ...and they are ROUTE settings: the manhwa tuning the plain
    # comic-text-detector route reads keeps its own panel-sized cap.
    from mangatl.detect import comictext as CT
    assert CT.tuning_for("manhwa")["craft_cap"] == 0.05
    assert "craft_low" not in CT.tuning_for("manhwa")


def test_craft_low_reaches_craft(monkeypatch):
    """`craft_low` is `low_text` on the CRAFT call, and None leaves CRAFT's
    own - a run with the knob unset must send exactly what it sent before."""
    import inspect
    from mangatl.detect import comictext as CT
    sig = inspect.signature(CT.detect_comictext)
    assert sig.parameters["craft_low"].default is None
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    assert 'knobs = {"low_text": craft_low} if craft_low is not None else {}' in src
    assert "_POOL.submit(_craft.pieces, img, **knobs)" in src


def test_what_the_balloon_model_did_not_cover_comes_in():
    got = [_r(100, 100, 200, 100)]
    n = WT._fill_in(got, [_r(400, 900, 180, 90, "sfx")], "all")
    assert n == 1 and len(got) == 2


def test_the_filled_in_boxes_land_in_reading_order():
    """A sound effect halfway down the page belongs where it is on the page,
    not after every balloon on it."""
    got = [_r(100, 900, 200, 100), _r(100, 100, 200, 100)]
    got.sort(key=lambda r: r.bbox[1])
    WT._fill_in(got, [_r(400, 500, 100, 100, "sfx")], "all")
    assert [r.bbox[1] for r in got] == [100, 500, 900]
    assert [r.id for r in got] == [0, 1, 2], "and renumbered with the order"


def test_the_sfx_only_filter_exists_and_is_not_the_default():
    """BOTH were built and measured, because lee asked for both: *"both both
    and evalue them against eacother"*. On ten pages of his chapter, 16 places
    with writing and 6 painted sounds:

        what is added            writing   sfx (whole)   stray   s/page
        A: only the sfx              14        1 (3 hit)    0      4.7
        B: everything not covered    15        2 (4 hit)    1      4.9

    B won on half a second, and the reason it won is the reason `"sfx"` is
    not the default: A filters on `kind`, and `kind` is the least trustworthy
    thing comic-text-detector produces. Of the five sounds it found there it
    called three `sfx` and the rest `bubble` or `freefloat` - so A threw away
    the big one on page 006 for being labelled `bubble`. Do not filter on the
    field that is wrong.

    It is kept because it is one word away for a chapter where the stray box
    matters more than the miss."""
    got = [_r(100, 100, 200, 100)]
    extra = [_r(400, 900, 180, 90, "sfx_big"), _r(400, 1400, 180, 90, "bubble")]
    assert WT._fill_in(list(got), list(extra), "sfx") == 1
    assert WT._fill_in(list(got), list(extra), "all") == 2
    assert WT._fill_in(list(got), list(extra), "") == 0
    assert WT.FILL == "all"


def test_craft_runs_only_when_sound_effects_were_asked_for():
    """lee: *"look online for better alternative for finding sfx"*. The best
    one is the one already installed - CRAFT finds four of the six painted
    sounds on his ten pages where the balloon models find none and the block
    head finds one - and the reason it was not on this route is cost.

    That cost is pixels, and the canvas was set for reading small printed
    writing. A painted sound is the largest thing on the page, so 1600
    instead of 2560 is about half the seconds AND finds more (see
    `CRAFT_CANVAS`). What is left of the cost is spent only when the sound
    effects tick is on, which is already a deliberate ask and the only thing
    CRAFT is here for: dialogue is found without it."""
    src = (PKG / "detect" / "webtoon.py").read_text(encoding="utf-8")
    body = src[src.index("def detect_webtoon("):src.index("def _fill_in(")]
    assert "if CRAFT_CANVAS and want_sfx:" in body
    assert 'k not in ("craft_x", "craft_y")' in body, \
        "dropped from the tuning, not passed as None beside it - the same "\
        "keyword twice is a TypeError, not an override"
    assert "craft_x=None, craft_y=None" not in body
    assert WT.CRAFT_CANVAS == 1600


def test_a_page_with_no_sound_effects_asked_for_pays_nothing_for_them(
        monkeypatch):
    """The tick is the switch. A chapter run without it must not spend a
    second in CRAFT, and the route must not hand its settings on."""
    from mangatl.detect import comictext as CT

    seen = {}

    def fake(page, w, **kw):
        seen.clear()
        seen.update(kw)
        page.seg_mask = np.zeros((40, 30), np.uint8)
        return []

    monkeypatch.setattr(CT, "detect_comictext", fake)
    monkeypatch.setattr(WT, "pieces", lambda *a, **k: [])
    page = Page(image=np.zeros((40, 30, 3), np.uint8), source_path="p.png")

    WT.detect_webtoon(page, "w.onnx", "k.onnx", want_sfx=False,
                      craft_x=0.3, craft_y=0.05)
    assert "craft_x" not in seen, seen

    WT.detect_webtoon(page, "w.onnx", "k.onnx", want_sfx=True,
                      craft_x=0.3, craft_y=0.05)
    assert seen.get("craft_x") == 0.3, seen
    assert seen.get("craft_y") == 0.05, seen


def test_the_mask_comes_from_the_same_forward_pass():
    """`detect_comictext` computes the segmentation it needs and leaves it on
    the page. Asking it for boxes therefore costs the mask this route was
    buying anyway plus its grouping - not a second pass through the net."""
    src = (PKG / "detect" / "webtoon.py").read_text(encoding="utf-8")
    body = src[src.index("def detect_webtoon("):src.index("def _fill_in(")]
    assert 'getattr(page, "seg_mask", None)' in body
    # ...and the plain mask call is still there for `fill=""`, or turning the
    # filling off would leave the route with no ink at all.
    assert "CT.page_text_mask(" in body
