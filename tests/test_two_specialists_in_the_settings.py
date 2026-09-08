"""Two specialist detectors, and a switch that only exists when it can run.

lee, after the head-to-head over 23 pages of Japanese: *"add a setting in teh
editor and make it run in teh editor"*, then *"this htuff shoud only be for
manga"*, then *"the setting should be in teh setting page not inthe fins text
popup"*.

So it is a project setting on the Settings page, read in ONE place, and Find
text does not ask about it at all -- a chapter is detected the same way every
time it is detected.

    comic-text-detector alone   5 missed  13 junk   2.9 s/page
    DBNet both ways + DB++/COO  3 missed   4 junk   9.9 s/page

Three things have to hold, and each of them is a way this could go quietly
wrong rather than loudly:

* **Off by default and off for a caller that never heard of it.** The route
  needs a 308MB checkpoint and a 116MB one that nobody has, and a project
  opened tomorrow must find Find text exactly as it left it.
* **Off when it cannot run.** A tick that does nothing is worse than no tick,
  so the row is not in the dialog unless both files are on the machine -- and
  when exactly one is, the row says which is missing rather than vanishing
  without explanation.
* **comic-text-detector still runs.** `inpaint` skips any region whose
  `text_mask is None`, three times over, so a page whose boxes came from two
  models that return rectangles and nothing else would not clean at all. The
  route borrows `comictext.page_text_mask` and the `weights` setting stays
  required.
"""
import tempfile

import pytest

from where import PKG

from mangatl.project import Project


def _p(**settings):
    d = tempfile.mkdtemp()
    p = Project(None, d)
    p.settings.setdefault("medium", "manga")
    p.settings.update(settings)
    return p


@pytest.fixture
def wheels(monkeypatch):
    """Say the two wheels the route needs are installed, whatever this machine
    has.

    `onomatopoeia.why_not` answers two different questions in one string: is the
    checkpoint on disk, and are torch, pyclipper and shapely importable. The
    tests below are about the FIRST - a written file and a project setting - and
    they were asserting the second by accident. On a machine with the wheels
    they passed; in CI, which installs numpy, opencv, pillow, pytest and
    fonttools and stops there, `two_specialists()` correctly answered False
    because there is no torch, and two tests reported that as a defect.

    Only the wheels half is stubbed. A missing FILE still says so, which is what
    `test_when_one_download_is_missing_the_row_says_which` is for.
    """
    from mangatl.detect import onomatopoeia
    real = onomatopoeia.why_not
    import os

    def only_the_file(path: str) -> str:
        if not path:
            return "no sound-effect weights are set"
        if not os.path.isfile(path):
            return "sound-effect weights are not at %s" % path
        return ""

    monkeypatch.setattr(onomatopoeia, "why_not", only_the_file)
    assert real is not onomatopoeia.why_not
    return only_the_file


# ------------------------------------------------- off unless somebody said so

def test_a_project_that_has_never_heard_of_it_has_it_off():
    assert _p().settings["two_specialists"] is False


def test_off_by_default_means_off_even_with_both_checkpoints(tmp_path):
    """The files being present is not consent."""
    ck = tmp_path / "detect-20241225.ckpt"
    ck.write_bytes(b"x")
    (tmp_path / "dbpp_coo.dat").write_bytes(b"x")
    (tmp_path / "w.onnx").write_bytes(b"x")
    p = _p(weights=str(tmp_path / "w.onnx"))
    assert p.dbnet_weights() and p.coo_weights()
    assert p.two_specialists() is False


def test_the_setting_is_the_only_thing_that_decides(tmp_path, wheels):
    """Find text used to carry a tick and does not any more -- one answer,
    read in one place, so a chapter is detected the same way every time."""
    import inspect
    for f in ("detect-20241225.ckpt", "dbpp_coo.dat", "w.onnx"):
        (tmp_path / f).write_bytes(b"x")
    p = _p(weights=str(tmp_path / "w.onnx"))
    assert p.two_specialists() is False
    p.settings["two_specialists"] = True
    assert p.two_specialists() is True
    assert list(inspect.signature(p.two_specialists).parameters) == []
    assert "two_specialists" not in inspect.signature(p.detect).parameters


# ------------------------------------------------- and only on manga

def test_it_is_offered_on_manga_and_nowhere_else(tmp_path, wheels):
    """lee: *"this htuff shoud only be for manga"*.

    Every number in the route came off 23 pages of Japanese. DBNet's training
    set is COMICS, the reaches were swept on manga fragments, the outside-text
    rule was checked against manga hand-set type. A manhwa is one tall column
    of colour with no panels across it and not one of those transfers.
    """
    for f in ("detect-20241225.ckpt", "dbpp_coo.dat", "w.onnx"):
        (tmp_path / f).write_bytes(b"x")
    for medium in ("manhwa", "manhua"):
        p = _p(weights=str(tmp_path / "w.onnx"), medium=medium,
               two_specialists=True)
        assert p.two_specialists() is False, medium
        assert "manga" in p.why_not_two_specialists(), medium
    p = _p(weights=str(tmp_path / "w.onnx"), medium="manga",
           two_specialists=True)
    assert p.two_specialists() is True
    assert p.why_not_two_specialists() == ""


def test_a_format_it_was_never_measured_on_is_not_shown_a_switch(tmp_path):
    """`partly` is what puts a disabled row on screen with the reason in it.
    A manga missing one download should see that; a manhwa should see
    nothing, because there is nothing it could download to make it apply."""
    for f in ("detect-20241225.ckpt", "w.onnx"):
        (tmp_path / f).write_bytes(b"x")
    src = (PKG / "project.py").read_text(encoding="utf-8")
    body = src[src.index('"two_specialists": {'):]
    body = body[:body.index('"why":')]
    # `route_here` IS `medium in TWO_MEDIA` for this route, said once for all
    # six cards - which is the point of it: `animetext` asked TWO_MEDIA here
    # for as long as those were the same set and went on asking it after they
    # stopped being. See `Project.route_media`.
    assert body.count('self.route_here("two_specialists")') == 2, body
    assert _p(medium="manhwa").summary()["two_specialists"]["partly"] is False
    assert _p(medium="manga").summary()["two_specialists"]["partly"] is True


def test_the_formats_are_named_in_one_place():
    from mangatl.project import Project as P
    assert P.TWO_MEDIA == ("manga",)


# ------------------------------------------------- and off when it cannot run

def test_a_tick_nobody_can_honour_is_not_honoured(tmp_path):
    """Ticked, and one checkpoint missing. The run must be the one that
    always worked, not an error and not a half-route."""
    (tmp_path / "detect-20241225.ckpt").write_bytes(b"x")
    (tmp_path / "w.onnx").write_bytes(b"x")
    p = _p(weights=str(tmp_path / "w.onnx"), two_specialists=True)
    assert p.coo_weights() == ""
    assert p.two_specialists() is False


def test_it_says_which_file_is_missing(tmp_path):
    """The route is comic-text-detector plus the sound-effect model now, so
    the file that can be absent is the sound-effect one."""
    (tmp_path / "w.onnx").write_bytes(b"x")
    p = _p(weights=str(tmp_path / "w.onnx"))
    why = p.why_not_two_specialists()
    assert why and "sound-effect" in why, why


def test_comic_text_detector_is_not_optional(tmp_path, monkeypatch):
    """It finds every line of dialogue AND the mask Clean paints with. The
    route only ever replaces its sound effects.

    The app's own folder is pointed somewhere empty on purpose: this asks what
    happens when comic-text-detector is genuinely absent, and the machine this
    runs on has a copy sitting next to the package that `detector_weights`
    would rightly find.
    """
    from mangatl import project as P
    monkeypatch.setattr(P, "__file__", str(tmp_path / "project.py"))
    coo = tmp_path / "dbpp_coo.dat"
    coo.write_bytes(b"x")
    p = _p(coo_weights=str(coo))
    why = p.why_not_two_specialists()
    assert "comic-text-detector" in why, why


# ------------------------------------------------- where the weights are found

def test_a_file_beside_the_detector_needs_no_setting(tmp_path):
    (tmp_path / "w.onnx").write_bytes(b"x")
    (tmp_path / "detect-20241225.ckpt").write_bytes(b"x")
    (tmp_path / "dbpp_coo.dat").write_bytes(b"x")
    p = _p(weights=str(tmp_path / "w.onnx"))
    assert p.dbnet_weights().endswith("detect-20241225.ckpt")
    assert p.coo_weights().endswith("dbpp_coo.dat")


def test_a_named_file_that_is_not_there_is_not_pretended_into_existence():
    p = _p(dbnet_weights="/no/such/file.ckpt")
    assert p.dbnet_weights() == ""


def test_a_named_file_beats_the_one_lying_beside(tmp_path):
    (tmp_path / "w.onnx").write_bytes(b"x")
    (tmp_path / "detect-20241225.ckpt").write_bytes(b"x")
    other = tmp_path / "mine.ckpt"
    other.write_bytes(b"x")
    p = _p(weights=str(tmp_path / "w.onnx"), dbnet_weights=str(other))
    assert p.dbnet_weights() == str(other)


def test_an_empty_box_looks_beside_the_app_before_giving_up(tmp_path,
                                                            monkeypatch):
    """lee: *"also the other detector are grey out"*, with every checkpoint
    sitting in the app's own folder and the "Model file" box empty.

    Empty used to mean give up: `_beside` anchored on `dirname(weights)`, an
    empty string has no dirname, and all three routes greyed themselves out
    saying comic-text-detector was needed - one directory listing away from
    the file they wanted. Empty now means LOOK where `get_models.py` puts it.
    """
    from mangatl import project as P
    (tmp_path / "comictextdetector.pt.onnx").write_bytes(b"x")
    (tmp_path / "dbpp_coo.dat").write_bytes(b"x")
    (tmp_path / "animetext.pt").write_bytes(b"x")
    monkeypatch.setattr(P, "__file__", str(tmp_path / "project.py"))
    p = _p()
    assert p.detector_weights().endswith("comictextdetector.pt.onnx")
    assert p.coo_weights().endswith("dbpp_coo.dat")
    assert p.animetext_weights().endswith("animetext.pt")


def test_a_typed_path_is_still_a_decision(tmp_path, monkeypatch):
    """A file named and not there stays empty. It does NOT fall back to the
    app's folder: a path somebody typed is a choice, and quietly running some
    other checkpoint instead is how you debug the wrong model for an hour."""
    from mangatl import project as P
    (tmp_path / "comictextdetector.pt.onnx").write_bytes(b"x")
    monkeypatch.setattr(P, "__file__", str(tmp_path / "project.py"))
    assert _p(weights="/no/such/detector.onnx").detector_weights() == ""


def test_no_detector_weights_anywhere_means_nothing_to_look_beside(tmp_path,
                                                                   monkeypatch):
    from mangatl import project as P
    monkeypatch.setattr(P, "__file__", str(tmp_path / "project.py"))
    assert _p().detector_weights() == ""
    assert _p().dbnet_weights() == ""
    assert _p().coo_weights() == ""


# ------------------------------------------------- and it is wired end to end

def test_find_text_does_not_ask():
    """The dialog had this tick for one turn and it is gone: a per-run choice
    and a project setting are two answers to one question."""
    src = (PKG / "project.py").read_text(encoding="utf-8")
    assert "if self.two_specialists() and weights:" in src
    ed = (PKG / "editor.py").read_text(encoding="utf-8")
    assert "two_specialists" not in ed
    js = (PKG / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")
    assert "two_specialists" not in js
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert 'id="kTwo"' not in html


def test_the_route_is_asked_before_comic_text_detector():
    """It falls through when the weights are absent, so it has to be first or
    the block head answers and it never gets a turn."""
    src = (PKG / "project.py").read_text(encoding="utf-8")
    body = src[src.index("def _detect_measured"):]
    assert body.index("self.two_specialists()") < \
        body.index('if detector == "comictext" and weights:')


def test_the_settings_page_saves_it_and_loads_it_back():
    """The card group holds the answer in `proj.settings`, not in a checkbox:
    reading a DOM element that no longer exists would save `false` on the next
    save of any unrelated setting. See `test_stop_means_stop`."""
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert "two_specialists:routeFlag('two_specialists')" in js
    assert "function currentRoute(" in js
    # ...and `routeFlag` is `currentRoute` for the cards THIS format offers
    # and a pass-through for the rest, so picking a card on a manga cannot
    # turn the webtoon default off for the manhwa in the same project.
    assert "function routeFlag(" in js


def test_there_is_no_model_file_box_to_get_out_of_step():
    """It came out. lee: *"remove the thig in teh screenshot it shoud happen
    in the backgeound"*.

    The bug it used to have is the reason it is worth a test either way:
    `saveSettings` sent `weights:$('weights').value` and nothing ever put the
    saved value INTO the box, so it came up blank on every load and the next
    save of any setting at all wrote that blank over the path - which is how
    lee's `weights` ended up "" with every checkpoint sitting in the app's own
    folder. A setting nothing on the screen edits cannot drift like that, but
    only if the save carries it through rather than reading a box that is not
    there."""
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert 'id="weights"' not in html
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert "$('weights')" not in js
    assert "weights:(proj.settings.weights||'')" in js


def test_an_empty_setting_still_means_look_beside_the_app():
    """Which is what makes the box removable at all: the download puts the
    file next to the app, and that is where an empty setting looks."""
    src = (PKG / "project.py").read_text(encoding="utf-8")
    body = src[src.index("def detector_weights("):]
    body = body[:body.index("\n    def ")]
    assert "self._weights_dir()" in body
    assert "CTD_FILES" in body
    # ...and a path put in a project by hand is still obeyed
    assert 'named = (self.settings.get("weights") or "").strip()' in body


def test_the_card_cannot_be_picked_until_the_files_are_there():
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert "function syncRoutes(" in js
    assert "c.disabled = !ready;" in js
    assert "syncRoutes();" in js, "and it is called when the settings load"


def test_the_page_is_told_whether_it_can_run():
    src = (PKG / "project.py").read_text(encoding="utf-8")
    assert '"two_specialists": {' in src
    for key in ('"ready":', '"partly":', '"why":'):
        assert key in src, key


def test_the_settings_page_has_the_card():
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert 'data-route="two_specialists"' in html
    assert 'class="card on"' not in html, "nothing starts selected in the markup"
    # ...and the cards ARE the detector choice now: the one-option menu they
    # used to sit under is gone, along with the second model path nothing has
    # called since the routes arrived. lee: *"clean up the whole detecot
    # setting page ... reeove redunced or duplicate settings"*.
    assert 'id="detector"' not in html
    assert 'id="text_weights"' not in html
    assert 'id="weights"' not in html, "and the model path went too" 


# --------------------------------------------- a grey card says why it is grey

def test_the_reason_is_written_on_the_card_that_is_grey():
    """lee: *"also the other detector are grey out"*.

    Every `why_not_*` on the Project returns a sentence somebody can act on -
    "ultralytics is not installed", "sound-effect weights are not at ...". The
    settings page collected them into ONE line under all four cards and then
    showed `why[0]`, so three greyed cards shared one sentence and none of
    them said which. The reason now goes on the card it belongs to.
    """
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    body = js[js.index("function syncRoutes("):js.index("function rateRoutes(")]
    assert "c.querySelector('.why')" in body, "the card carries its own reason"
    assert "note.textContent = st.why" in body
    assert "c.appendChild(note)" in body
    assert "c.title = st.why" in body, "and it is the button's tooltip too"
    # ...and the reason comes off again when the file turns up.
    assert "note.remove()" in body
    # The old shared line no longer picks a winner out of the reasons.
    assert "why[0]" not in body, "one sentence for four cards is what broke"


def test_the_reason_stays_readable_through_the_disabled_fade():
    """A disabled card is drawn at .45 opacity. The reason is the one thing on
    it somebody has to be able to read, so it is not faded with the rest."""
    css = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")
    rule = css[css.index(".cards .card .why{"):]
    rule = rule[:rule.index("}")]
    assert "opacity:1" in rule


def test_every_reason_is_a_sentence_somebody_can_act_on():
    """A card that greys out with an empty reason is a dead end. Each of the
    three routes must answer for both ways it can fail: no file named, and a
    file named that is not there."""
    from mangatl.detect import animetext, mangaseg, onomatopoeia
    for mod in (animetext, mangaseg, onomatopoeia):
        assert mod.why_not("").strip(), mod.__name__
        assert "/nope" in mod.why_not("/nope"), mod.__name__


# ------------------------------------------------- the pieces it is made of

def test_the_two_detectors_say_why_they_cannot_run():
    from mangatl.detect import dbtext, onomatopoeia
    assert "no manga-text weights" in dbtext.why_not("")
    assert "not at /nope" in dbtext.why_not("/nope")
    assert "no sound-effect weights" in onomatopoeia.why_not("")


def test_the_sound_effect_model_runs_at_the_size_it_was_measured_at():
    """1152 upscales a 960-wide manga page: same 80 boxes, 8.43 s/page
    instead of 2.38, and twice the junk."""
    from mangatl.detect import onomatopoeia
    assert onomatopoeia.SIDE == 640


def test_dbnet_reads_the_page_both_ways_by_default():
    """A DB head is trained on dark strokes on light ground, so a caption
    reversed out of a black balloon is invisible to it."""
    import inspect
    from mangatl.detect import dbtext
    sig = inspect.signature(dbtext.pieces)
    assert sig.parameters["both_ways"].default is True


def test_the_two_pools_never_reach_across():
    """lee: *"sfx and outide ext shodu not be welded and bubble text shoud
    only weled to text very close to them"*."""
    from mangatl.detect import dbcoo
    assert dbcoo.TEXT_X < dbcoo.SFX_X and dbcoo.TEXT_Y < dbcoo.SFX_Y
    src = (PKG / "detect" / "dbcoo.py").read_text(encoding="utf-8")
    body = src[src.index("def grouped("):src.index("def regions_from(")]
    assert "_pool(dbtext.pieces" in body and "_pool(raw_sfx" in body
    assert body.count("_pool(") == 2, "one grouping per pool, never a merged one"


def test_the_ctd_box_wins_every_duplicate():
    """lee: *"if there are duplicates keep teh ctd boxes"*. Not the bigger
    one and not the first one -- a CTD box carries a `seg` mask measured on
    the ink, and a COO box is a rectangle round a probability blob."""
    src = (PKG / "detect" / "dbcoo.py").read_text(encoding="utf-8")
    body = src[src.index("def detect_ctd_sfx("):src.index("def why_not(")]
    # The sound-effect family is still handled apart from the rest. It used
    # to be by leaving it out of the balloon pass entirely; it is now by
    # refusing to DEMOTE it there, because leaving it out was what made
    # dialogue inside a balloon come back `sfx` with no way back. See
    # `test_the_balloon_outranks_the_specialist`.
    assert '_kinds.family_of(r.kind) == "sfx"' in body, \
        "it has to treat comic-text-detector's own sound effects apart"
    assert "fresh = [g for g in groups" in body
    assert "want_sfx=False" in body


def test_the_mask_is_not_computed_twice():
    """`detect_comictext` already built it; running that net again for the
    same answer cost 2.29s of 9.44 a page."""
    ct = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    assert "page.seg_mask = tmask" in ct
    src = (PKG / "detect" / "dbcoo.py").read_text(encoding="utf-8")
    assert 'tmask = getattr(page, "seg_mask", None)' in src


def test_a_fragment_of_paint_is_not_agreement():
    """The ぶ of ぶぶぶっっっ is one clean character of a painted effect, and
    DBNet reads it. `BIGGER` is what tells that from hand-set type, and it
    has to be over 1 or the effect that agrees about ほか IS ほか."""
    from mangatl.detect import dbcoo
    assert dbcoo.BIGGER > 1.0


def test_every_box_the_route_makes_carries_a_mask():
    """`inpaint` skips a region whose `text_mask is None`, so a route that
    handed back bare rectangles would clean nothing at all."""
    src = (PKG / "detect" / "dbcoo.py").read_text(encoding="utf-8")
    assert "CT.page_text_mask(" in src
    body = src[src.index("def regions_from("):src.index("def why_not(")]
    assert "text_mask=(text.astype(np.uint8) * 255)" in body
    assert "if int(text.sum()) < MIN_INK:\n            continue" in body


def test_the_mask_head_is_still_comic_text_detectors():
    from mangatl.detect import comictext
    assert callable(comictext.page_text_mask)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
