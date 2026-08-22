"""One detector instead of two, and a bracket is not a piece of writing.

lee, having read what `deepghs/AnimeText_yolo` reports: *"impliment the animen
text alone and maybe add ctd as a mask if needed"*, and then, over two crops of
014's shop panel: *"alaso removethe bigger box that are around ground like
this"*.

## WHAT IT DOES ON THE TEST CHAPTER

    what                 found   missed
    bubble text            130        0     ALL of it
    outside text            29        0     ALL of it
    sound effects           56        5
    sites nothing boxes      0        6

    route                        missed  junk  models  s/page
    comic-text-detector alone         5    13     1      2.94
    CTD + COO + the rules             6     4     2      9.9
    Manga109 seg + COO + CTD mask     7     3     3     12.7
    AnimeText + COO + CTD mask       11     1     3     14.5

Eleven reads worse than six and is not: six of the eleven are the same six
every route on this chapter misses, and the other five are sound effects.
**Every one of the 159 boxes somebody has to translate is found**, which
nothing else here has managed, with one junk box on 23 pages.

Four things have to hold:

* **comic-text-detector still runs.** `inpaint` skips a region whose
  `text_mask is None`, three times over, and AnimeText is a detector with no
  masks at all. That is the "if needed" and it is needed.
* **The sound-effect model is optional and the bubbles are not.** AnimeText
  has ONE class, so without COO there is no sfx family and painted type
  comes back as dialogue -- 179 bubble boxes against 149.
* **A box round other boxes is dropped**, and only when it holds at least
  two: one is the duplicate case, which `_drop_duplicates` settles by keeping
  the better box rather than blindly the smaller.
* **Off by default and off without the checkpoint**, on manga only.
"""
import tempfile

import pytest

from where import PKG

from mangatl.detect import animetext, dbcoo
from mangatl.project import Project


def _p(**settings):
    d = tempfile.mkdtemp()
    p = Project(None, d)
    p.settings.setdefault("medium", "manga")
    p.settings.update(settings)
    return p


def test_it_is_on_by_default_and_still_gated_by_the_checkpoint(tmp_path,
                                                               monkeypatch):
    """lee: *"make anime text teh default detector"*. The SETTING defaults
    on; the ROUTE still refuses to run without the 53MB checkpoint, so a
    machine that never downloaded it falls back to comic-text-detector and
    loses nothing.

    The second half is asked of a machine with NO checkpoints, on purpose: it
    used to be asked of whatever was lying beside the app, so it passed on a
    bare checkout and failed on any machine that had actually downloaded the
    file - which is every machine the app runs on."""
    assert _p().settings.get("animetext") is True
    from mangatl import project as P
    monkeypatch.setattr(P, "__file__", str(tmp_path / "project.py"))
    assert not _p().animetext()


def test_it_is_off_without_the_checkpoint(tmp_path):
    """`_beside` answers "" for a path that is not there, the same as for a
    machine that has never downloaded anything -- so the sentence is the
    same one the other two routes give, and it is not a traceback.

    comic-text-detector is a REAL file here. `detector_weights` checks that
    the named path exists rather than that the box is non-empty, so a made-up
    `x.onnx` would answer for the mask instead and hide what this asks.
    """
    ctd = tmp_path / "comictextdetector.pt.onnx"
    ctd.write_bytes(b"x")
    p = _p(animetext=True, weights=str(ctd), animetext_weights="nope.pt")
    assert not p.animetext()
    assert "AnimeText weights" in p.why_not_animetext()


def test_it_is_off_on_a_manhwa():
    p = _p(medium="manhwa", animetext=True, weights="x.onnx")
    assert not p.animetext()
    assert "manga" in p.why_not_animetext()


def test_the_clean_mask_is_still_required(tmp_path, monkeypatch):
    """A route whose boxes carry no mask would not clean at all.

    The app's own folder is pointed somewhere empty: an empty "Model file" box
    now LOOKS beside the app before giving up, and the machine this runs on
    has a copy there.
    """
    from mangatl import project as P
    monkeypatch.setattr(P, "__file__", str(tmp_path / "project.py"))
    p = _p(animetext=True, weights="")
    assert "comic-text-detector" in p.why_not_animetext()


@pytest.mark.parametrize("name", ["animetext.pt", "yolo12l_animetext.pt",
                                  "model.pt"])
def test_every_name_it_might_be_saved_under_is_found(name, tmp_path):
    """`model.pt` is what Hugging Face calls it and what lands in Downloads.

    Exercised through `_beside` rather than read out of the source, because
    what matters is that a file sitting next to the detector is FOUND.
    """
    (tmp_path / name).write_bytes(b"x")
    p = _p(animetext=True, weights=str(tmp_path / "ctd.onnx"))
    assert p.animetext_weights() == str(tmp_path / name)


def test_a_name_it_is_not_saved_under_is_not_picked_up(tmp_path):
    (tmp_path / "something-else.pt").write_bytes(b"x")
    p = _p(animetext=True, weights=str(tmp_path / "ctd.onnx"))
    assert p.animetext_weights() == ""


def test_no_weights_says_so():
    assert "no AnimeText weights" in animetext.why_not("")


def test_a_missing_wheel_is_a_sentence_rather_than_a_traceback(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "ultralytics":
            raise ImportError("no")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    assert "ultralytics" in animetext.why_not(str(PKG / "project.py"))


def test_the_size_is_the_measured_knee():
    """1024 is one junk box; 1280 is none and twice the time."""
    assert animetext.SIZE == 1024


def test_the_one_class_is_named_not_numbered():
    assert animetext.TEXT == "text_block"


def test_the_dialog_is_told_all_three_answers():
    st = _p(animetext=True, weights="x.onnx").summary()["animetext"]
    assert set(st) == {"ready", "partly", "on", "why"}


def test_a_manhwa_is_not_offered_the_row_at_all():
    st = _p(medium="manhwa", animetext=True).summary()["animetext"]
    assert not st["ready"] and not st["partly"]


# --- a box round other boxes is a bracket -------------------------------

def _b(x0, y0, x1, y1, name="text"):
    return ((x0, y0, x1, y1), name)


def test_the_bracket_round_three_lines_goes():
    """014's shop panel: one rectangle over three columns of a balloon."""
    boxes = [_b(0, 0, 300, 400), _b(10, 10, 90, 390), _b(110, 10, 190, 390),
             _b(210, 10, 290, 390)]
    out = dbcoo._without_the_box_around_the_group(boxes)
    assert len(out) == 3
    assert (0, 0, 300, 400) not in [b for b, _n in out]


def test_a_box_holding_one_other_is_left_alone():
    """That is the duplicate case and `_drop_duplicates` settles it."""
    boxes = [_b(0, 0, 300, 400), _b(10, 10, 290, 390)]
    assert len(dbcoo._without_the_box_around_the_group(boxes)) == 2


def test_boxes_merely_beside_each_other_are_all_kept():
    boxes = [_b(0, 0, 100, 100), _b(200, 0, 300, 100), _b(400, 0, 500, 100)]
    assert len(dbcoo._without_the_box_around_the_group(boxes)) == 3


def test_a_box_grazed_by_smaller_neighbours_is_not_a_bracket():
    """Held means held: `NEST_IN` of the SMALLER has to be inside the bigger.

    Both neighbours here are smaller and both overlap, which is what a
    bracket looks like from the outside -- but each of them hangs mostly
    outside, so neither is a thing this box is drawn around.
    """
    boxes = [_b(0, 0, 200, 200), _b(180, 0, 260, 80), _b(-60, 120, 20, 200)]
    assert len(dbcoo._without_the_box_around_the_group(boxes)) == 3


def test_the_smaller_boxes_are_the_ones_kept():
    boxes = [_b(0, 0, 300, 400), _b(10, 10, 90, 390), _b(110, 10, 190, 390)]
    out = [b for b, _n in dbcoo._without_the_box_around_the_group(boxes)]
    assert all((b[2] - b[0]) < 300 for b in out)


def test_the_bracket_test_is_on_by_default_in_the_route():
    import inspect
    sig = inspect.signature(dbcoo.detect_animetext)
    assert sig.parameters["drop_nested"].default == dbcoo.NEST_IN
    assert dbcoo.NEST_LEAST == 2
    # ...and it reads the module's number rather than carrying a copy of it,
    # which no comparison of VALUES can tell: a route defaulting to a literal
    # 0.7 would go on bracketing the day the bar here moves.
    src = inspect.getsource(dbcoo.detect_animetext)
    assert "drop_nested: float = NEST_IN" in src


def test_the_route_reads_every_switch_rather_than_its_own_numbers():
    import inspect
    sig = inspect.signature(dbcoo.detect_animetext)
    assert sig.parameters["split_sfx"].default is dbcoo.SPLIT_SFX
    assert sig.parameters["split_texts"].default is dbcoo.SPLIT_TEXTS


def test_the_sound_effect_model_is_optional():
    """AnimeText alone has no sfx family; the signature has to allow both."""
    import inspect
    sig = inspect.signature(dbcoo.detect_animetext)
    assert sig.parameters["coo_ckpt"].default == ""


def test_the_settings_page_has_a_card_for_it():
    """The three routes are one card group now, not three ticks --
    see `test_stop_means_stop`. The invariant is the same: it is on
    the Settings page, it says why it cannot run, and it is drawn
    when the settings load."""
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert 'data-route="animetext"' in html
    assert 'id="routeWhy"' in html
    assert "'animetext'" in js, "the route is one the picker knows"
    assert "function syncRoutes(" in js
    assert "syncRoutes();" in js


@pytest.mark.parametrize("medium", ["manhwa", "manhua", "webtoon"])
def test_only_manga(medium):
    assert not _p(medium=medium, animetext=True, weights="x.onnx").animetext()
