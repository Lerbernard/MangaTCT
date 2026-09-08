"""Stop cancels the page it is on, not the page after it.

lee: *"can you make stopping a proccess happen fast it shoud cancel teh page
it woirkingg on and stop not keep finishing it"*.

`job["cancel"]` was read in exactly one place -- between pages in
`_run_one` -- so Stop meant "stop after this one", and on a textured page a
clean is the slowest thing the app does. `stopping` gives the inner loops a
flag to read and an exception to raise; `_run_one` owns setting and clearing
it, and treats `Stopped` as a cancelled run rather than as an error.

## AND THE ROUTES ARE ONE CHOICE, NOT FOUR TICKS

lee, in the same breath: *"make all teh detectore selecteabe card in the
setting so i can pick and choos and mek them nice"*, then *"also add time
estimation and a quality rattoing on each box"*.

They were three independent checkboxes and independence was a lie:
`_detect_measured` asks them in order and the first yes wins, so two ticked
meant one silently ignored. One card is selected, the server still gets three
booleans, and exactly one of them is true.
"""
from where import PKG

from mangatl import stopping


def teardown_function():
    stopping.clear()


def test_nothing_stops_when_nobody_is_watching():
    """The default state, and the one every test and CLI run is in."""
    stopping.clear()
    assert stopping.asked() is False
    stopping.check()          # must not raise


def test_check_raises_once_stop_is_asked_for():
    stopping.watch(lambda: True)
    assert stopping.asked() is True
    try:
        stopping.check()
    except stopping.Stopped:
        return
    raise AssertionError("check() did not raise")


def test_check_is_silent_while_the_run_is_wanted():
    stopping.watch(lambda: False)
    stopping.check()
    assert stopping.asked() is False


def test_clear_really_clears():
    """A flag left set would stop the NEXT run before it started."""
    stopping.watch(lambda: True)
    stopping.clear()
    assert stopping.asked() is False
    stopping.check()


def test_a_watcher_that_explodes_reads_as_no():
    """"The user clicked Stop" must never become a crash report."""
    def bad():
        raise RuntimeError("boom")
    stopping.watch(bad)
    assert stopping.asked() is False
    stopping.check()


def test_stopped_is_an_exception_of_its_own():
    """Caught by name in `_run_one`, so it cannot be a bare Exception."""
    assert issubclass(stopping.Stopped, Exception)
    assert stopping.Stopped is not Exception


def test_the_slow_loops_all_have_a_checkpoint():
    """OCR, cleaning and translation are the three things worth stopping.

    Asked of the source because the alternative is standing up a page, an
    engine and a network for each -- and what could regress is somebody
    deleting the line, which reading the source catches exactly.
    """
    for mod, near in (
            ("ocr.py", "Somebody's own text box stands for no writing"),
            ("inpaint.py", "sound effects USED to be skipped wholesale"),
            ("translate.py", "for n, group in enumerate(groups, 1):")):
        src = (PKG / mod).read_text(encoding="utf-8")
        at = src.index(near)
        # the checkpoint sits just ABOVE the landmark, at the top of the loop
        assert "_stopping.check()" in src[max(0, at - 400):at + 500], mod


def test_the_slow_detector_is_broken_into_three_stoppable_pieces():
    """lee: *"also stopping is taling a long time still"*.

    Detection is the slowest step, and the classical branch - what runs when
    comic-text-detector is not there - is three whole-page passes back to
    back. A Stop pressed inside them used to sit there for the rest of the
    page: the only checkpoint was at the TOP, which helps a page that has not
    started and nothing else. There is no per-region loop to hang one on, so
    they go BETWEEN the passes.
    """
    src = (PKG / "project.py").read_text(encoding="utf-8")
    body = src[src.index("def _detect_measured"):]
    body = body[:body.index("\n        return found")]
    assert body.count("_stopping.check()") >= 2, \
        "the classical branch needs a way out between its passes"
    at = body.index("_ft.read_the_writing(page, found)")
    assert "_stopping.check()" in body[at:at + 300], \
        "and one straight after the reader, which is the slowest of the three"


def test_the_job_loop_owns_the_flag_and_gives_it_back():
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def _run_one("):src.index("def _dispatch(")]
    assert "_stopping.watch(" in body
    assert "_stopping.clear()" in body
    # ...and the clear is in the `finally`, not on the happy path.
    assert body.index("_stopping.clear()") > body.index("finally:")


def test_a_stopped_run_is_not_an_error():
    """Red bar for a crash, quiet for a change of mind."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def _run_one("):src.index("def _dispatch(")]
    assert "except _stopping.Stopped:" in body
    # caught BEFORE the general handler, or the general one wins
    assert body.index("except _stopping.Stopped:") < \
        body.index("except Exception as e:")


# --- the routes, as one choice ------------------------------------------

def _js():
    return (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")


def _html():
    return (PKG / "static" / "editor.html").read_text(encoding="utf-8")


def test_there_is_a_card_for_every_route_and_one_for_none_of_them():
    html = _html()
    for route in ("", "two_specialists", "manga_segmenter", "animetext",
                  "webtoon_ko", "webtoon_zh"):
        assert 'data-route="%s"' % route in html, route


def test_every_card_carries_what_it_costs_and_how_good_it_is():
    """lee asked for both, and a card with neither is four words and a shrug."""
    html = _html()
    # `data-sec=` alone also matches the settings rail's sections, so the
    # count is taken on the two attributes only these cards have.
    #
    # SIX CARDS, FOUR ON SCREEN. Two were counted on manga fragments, two on
    # webtoons, and two on both - and the group shows the ones that belong to
    # the format being worked on. A card counted on both carries both sets:
    # `data-missed` is 23 pages of Japanese and `data-wmissed` is lee's
    # Korean chapter. See `ROUTE_MEDIA` in project.js.
    assert html.count("data-missed=") == 4
    assert html.count("data-wmissed=") == 4
    assert html.count("data-junk=") == 4
    assert html.count("data-wjunk=") == 4
    assert html.count('class="est"') == 6
    # The bar and the percentage are gone - three words instead, and on every
    # choice rather than only on the one that happens to have a count. See
    # `RATE_WORDS` in project.js. lee: *"remove teh blue bar and the number
    # and create a new ratting system, fair, good and great"*.
    assert html.count('class="rating"') >= 4
    assert 'class="rate"' not in html and 'class="score"' not in html


def test_the_selection_is_read_from_the_settings_not_from_the_dom():
    """The checkboxes are gone. Reading them would save `false` for all three
    on the next save of any unrelated setting, and the choice would vanish."""
    js = _js()
    for k in ("two_specialists", "manga_segmenter", "animetext",
              "webtoon_ko", "webtoon_zh"):
        assert "%s:routeFlag('%s')" % (k, k) in js, k
    assert "$('animetext').checked" not in js
    # ...and `routeFlag` is `currentRoute` for the cards this format offers
    # and a pass-through for the ones it does not, so a save on a manga
    # cannot decide the manhwa's route. See `test_a_webtoon_gets_a_webtoon
    # _detector`.
    fn = js[js.index("function routeFlag("):]
    assert "currentRoute() === k" in fn[:fn.index("\n}")]


def test_only_one_route_can_be_on():
    """`_detect_measured` asks them in order and the first yes wins, so two
    ticked meant one ignored."""
    js = _js()
    body = js[js.index("function pickRoute("):js.index("function syncRoutes(")]
    assert "if(routeHere(k)) proj.settings[k] = (k === name)" in body


def test_a_route_whose_weights_are_missing_cannot_be_picked():
    js = _js()
    body = js[js.index("function pickRoute("):js.index("function syncRoutes(")]
    assert "if(name && (!st || !st.ready)) return;" in body


def test_the_rating_says_what_it_is_made_of():
    """A score whose formula is a secret is a score nobody can argue with."""
    js = _js()
    assert "(SITES - missed - junk)" in js
    assert "hand-checked " in js and "' right - '" in js
    # ...and which count, because there are two: 226 hand-checked sites on 23
    # pages of Japanese manga, and 33 balloons and captions on lee's Korean
    # chapter. Showing either on the other format would be a made-up number.
    assert "const WEBTOON_SITES = 33;" in js
    assert "SITES = strip ? WEBTOON_SITES : 226" in js


def test_the_estimate_is_for_this_chapter_not_for_one_page():
    js = _js()
    assert "proj.pages.length" in js
    assert "' for ' + pages + ' page'" in js
    # ...and the seconds are actually MULTIPLIED by the page count. Reading
    # the page count and then not using it is the shape this catches.
    assert "const secs = sec * (pages || 0);" in js


# --- and the box-select tool --------------------------------------------

def _bs():
    return (PKG / "static" / "js" / "boxselect.js").read_text(encoding="utf-8")


def test_s_arms_the_box_select_tool():
    src = _bs()
    assert "e.key === 's' || e.key === 'S'" in src
    assert "toggleBoxSelect()" in src


def test_it_is_not_armed_while_somebody_is_typing():
    """"s" is a letter, and the editor is full of text fields."""
    src = _bs()
    assert "INPUT|TEXTAREA|SELECT" in src
    assert "isContentEditable" in src


def test_touching_a_box_is_enough_to_take_it():
    """Containment is the tidier rule and the wrong one: a column of Japanese
    runs to the edge of its panel."""
    src = _bs()
    assert "bx < x1 && bx + bw > x0 && by < y1 && by + bh > y0" in src


def test_it_fills_the_selection_everything_else_already_uses():
    src = _bs()
    assert "selMulti" in src
    assert "renderList" in src


def test_shift_adds_rather_than_replaces():
    src = _bs()
    assert "e.shiftKey" in src


def test_it_stays_armed_after_a_drag():
    """It used to put itself away after one use. lee: *"make the selevct
    button be persistent and not turn off after one use"* - the next thing
    after selecting twelve boxes was selecting twelve more, and re-arming per
    panel is worse than one Escape at the end. So a finished drag leaves the
    tool up, a click-not-a-drag clears the selection and leaves it up too,
    and the ONLY ways out are the deliberate ones: "s", Escape, the button.
    """
    src = _bs()
    body = src[src.index("function _bsUp("):src.index("window.addEventListener")]
    assert "toggleBoxSelect(false)" not in body,         "nothing inside a drag may put the tool away"
    # the click-not-a-drag branch deselects rather than disarms
    assert "selMulti.clear(); sel = null;" in body
    # ...and the deliberate ways out are still wired
    assert "if(e.key === 's' || e.key === 'S'){ toggleBoxSelect();" in src
    assert "e.key === 'Escape' && boxSel" in src


def test_the_buttons_are_filled_not_outlined():
    """lee, over a screenshot of the outlined pill: *"do you see this border
    thing you kike to do  make the wole bacground the color not just a border
    area foe evry button like this"*. So every button on the row is FILLED
    with its own colour - the kind buttons carry theirs as `--lgc` inline, the
    select tool sets its blue in CSS, and the armed select is solid."""
    css = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")
    base = css[css.index(".legend .lgmain{"):]
    base = base[:base.index("}")]
    assert "background:transparent" not in base, "the border thing is over"
    assert "color-mix" in base and "var(--lgc" in base
    js = (PKG / "static" / "js" / "panels.js").read_text(encoding="utf-8")
    assert 'style="--lgc:${KIND_COLORS[f]}"' in js,         "each kind button hands its colour to the fill"
    assert ".legend .lgmain.lgsel{--lgc:#2f6fd0" in css
    on = css[css.index(".legend .lgmain.lgsel.on{"):]
    on = on[:on.index("}")]
    assert "background:#2f6fd0" in on, "armed is solid, not merely outlined"


def test_it_is_on_the_page_and_NOT_in_the_toolbox():
    """It moved, and this test was left behind by the move.

    It used to be a tool on the strip down the left. lee: *"i wasnt you tpo
    make teh select tool only be usable on the translation tab"* - it picks
    BOXES, and boxes are managed on the Translation view, where that strip is
    not even up. So the one tool on it that belonged to the other view sat
    there being armable from the wrong screen.

    Where it lives now is where it always also lived: the legend row above the
    page, off the same `boxSel` state, so the S key and the button and the mode
    cannot disagree. `toolbar.js` says all of that where the slot used to be.

    The test asserting it is in the toolbox outlived that by a week, and it is
    the toolbox half that was wrong - so it is asserted the other way round
    here, which is a thing this test can say and a missing button is not.
    """
    tb = (PKG / "static" / "js" / "toolbar.js").read_text(encoding="utf-8")
    assert "Select boxes (S)" not in tb, \
        "the box-select tool is back on the strip it was taken off"
    panels = (PKG / "static" / "js" / "panels.js").read_text(encoding="utf-8")
    assert "toggleBoxSelect()" in panels, "the legend has no button for it"
    assert "Select boxes" in panels
    assert "boxselect.js" in _html()


# --- and merging what the square selected ------------------------------

def _ro():
    return (PKG / "static" / "js" / "region-ops.js").read_text(encoding="utf-8")


def test_two_boxes_are_needed_before_anything_merges():
    src = _ro()
    body = src[src.index("async function mergeSelected("):]
    body = body[:body.index("\n}")]
    assert "if(ids.length < 2)" in body


def test_the_old_boxes_go_and_one_new_one_is_drawn():
    """lee: *"it shoud dlete the curent boxes and make a new box taht fits all
    the boxes inside of it"*.

    Resizing the first box was tried and did not hold: a region carries
    `bbox`, `draw_box` and a fitted `bubble_bbox`, and the server re-measures
    some of them from the ink under the new rectangle. A fresh box has no
    history to fight."""
    src = _ro()
    body = src[src.index("async function mergeSelected("):]
    body = body[:body.index("\n}")]
    assert "for(const r of rs) await api(`/api/page/${cur}/region/${r.id}`, 'DELETE');" in body
    at_del = body.index("'DELETE'")
    at_new = body.index("await api(`/api/page/${cur}/region`, 'POST'")
    assert at_del < at_new, "the old boxes go first"


def test_the_union_of_every_rectangle_is_taken():
    """Not the first box's, and not the biggest one's."""
    src = _ro()
    for line in ("Math.min(...rs.map(r => r.bbox[0]))",
                 "Math.min(...rs.map(r => r.bbox[1]))",
                 "Math.max(...rs.map(r => r.bbox[0] + r.bbox[2]))",
                 "Math.max(...rs.map(r => r.bbox[1] + r.bbox[3]))"):
        assert line in src, line


def test_no_text_is_silently_dropped():
    """A translator who finds half a sentence gone has no way to know it was
    ever there, so every box's words are kept and joined in reading order."""
    src = _ro()
    assert "const join = (k) => rs.map(r => (r[k] || '').trim())" in src
    assert "join('src_text')" in src and "join('dst_text')" in src


def test_the_boxes_are_merged_in_reading_order():
    src = _ro()
    body = src[src.index("async function mergeSelected("):]
    assert "(a.order ?? 0) - (b.order ?? 0)" in body[:900]


def test_a_merge_is_one_undo_press():
    """Four presses to undo one merge is a merge nobody trusts."""
    src = _ro()
    body = src[src.index("async function mergeSelected("):]
    body = body[:body.index("\n}")]
    assert "record('region-merge'" in body
    assert "restoreRegions(pg, snaps)" in body


def test_the_sidebar_offers_it_only_when_there_is_a_selection():
    js = (PKG / "static" / "js" / "panels.js").read_text(encoding="utf-8")
    assert "mergeSelected()" in js
    at = js.index("mergeSelected()")
    assert "selMulti.size>1" in js[max(0, at - 300):at]


def test_m_merges_when_boxes_are_selected_and_marks_pixels_otherwise():
    """M was the pixel marquee. They cannot both have it, and they do not have
    to: the selection says which one M could possibly mean.

    The two halves sit in different places now. Merging works on every view,
    so it is checked BEFORE the gate that limits the paint tools to the
    typeset view; the marquee is a paint tool and stays below it. lee found
    that gap the hard way: *"clik m ... nothing happens"*."""
    js = (PKG / "static" / "js" / "select.js").read_text(encoding="utf-8")
    merge = js[js.index("(e.key==='m'||e.key==='M')"):][:400]
    assert "selMulti.size>1" in merge
    assert "mergeSelected()" in merge
    at = js.index("if(e.key==='m'||e.key==='M') toggleSelTool('rect');")
    assert js.index("view!=='typeset'") < at, "the marquee is a paint tool"


def test_the_legend_row_carries_the_select_tool_too():
    """lee, over the legend: *"also add teh select button in here as a
    slecteable button"*. Same state as the toolbox, so the two cannot
    disagree about whether it is armed."""
    js = (PKG / "static" / "js" / "panels.js").read_text(encoding="utf-8")
    body = js[js.index("function renderLegend("):]
    body = body[:body.index("el.innerHTML=bits.join('');")]
    assert "toggleBoxSelect()" in body
    assert "boxSel" in body, "it lights off the tool's own state"


def test_arming_the_tool_redraws_both_places_that_show_it():
    src = (PKG / "static" / "js" / "boxselect.js").read_text(encoding="utf-8")
    assert "drawToolbox()" in src
    assert "renderLegend()" in src


def test_the_family_is_called_freefloat_where_people_read_it():
    """lee: *"rename outide boxes as freefloat boxes everywhere"*."""
    from mangatl import kinds
    assert kinds.FAMILY_LABELS["freefloat"] == "Freefloat text"
    js = (PKG / "static" / "js" / "frames.js").read_text(encoding="utf-8")
    assert "freefloat:'Freefloat text'" in js
    assert "freefloat:'Outside text'" not in js


def test_a_null_polygon_clears_rather_than_crashes():
    """lee hit this merging boxes:

        pts = [[int(a), int(b)] for a, b in body["polygon"]]
        TypeError: 'NoneType' object is not iterable

    `"polygon" in body` was the test, so a caller sending `null` to CLEAR one
    walked straight into iterating it. Null means the box has no polygon,
    which is what a plain rectangle already is."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    assert 'elif body.get("polygon") is not None:' in src
    assert 'elif "polygon" in body:' not in src
