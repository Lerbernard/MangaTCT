"""A third specialist, and the one that finally answers the balloon question.

lee, shown what `ShadowB/Manga109-panel-balloon-text-yolov26-segmentation`
does on his chapter: *"ok impliment it"*.

    what                  found   missed          junk
    bubble text             129        1   99.2%     0
    outside text             23        6             0
    sound effects             4       57             0

Zero false boxes over 23 pages, at 0.86 s. No other detector here has managed
one page of that. It is blind to onomatopoeia because Manga109 does not
annotate painted effects as text, which is why COO still runs.

    route                         missed  junk  s/page  bubble boxes
    comic-text-detector alone          5    13    2.94
    CTD + COO + the rules              6     4     7.5           132
    Manga109 seg + COO + CTD mask      7     3    11.0           142

Four things have to hold:

* **comic-text-detector does not leave.** The segmenter's masks are
  REGION-level -- 0.659 of a box against CTD's 0.342, one a blob over the
  text area and the other the strokes -- and `inpaint` paints what the mask
  calls writing. So the ink still comes from `page_text_mask`.
* **The balloon shape outranks the sound-effect model.** A drawn balloon is
  the strongest evidence there is, and it is now a shape a model segmented
  rather than a run of paper a Canny pass inferred.
* **comic-text-detector fills the margins**, gated on the same bar as
  everything else it is trusted with. The segmenter's six extra misses are
  all page furniture -- credits, the title block, a page-number strip --
  because Manga109 annotates what is drawn in the story and not the strip
  along the bottom of the page.
* **It is off unless it can run.** A 23MB checkpoint nobody has by default
  and an `ultralytics` nobody has either.
"""
import tempfile

import pytest

from where import PKG

from mangatl.detect import dbcoo, mangaseg
from mangatl.project import Project


def _p(**settings):
    d = tempfile.mkdtemp()
    p = Project(None, d)
    p.settings.setdefault("medium", "manga")
    p.settings.update(settings)
    return p


def test_it_is_off_by_default():
    assert _p().settings.get("manga_segmenter") in (False, None)
    assert _p().manga_segmenter() is False


def test_it_is_off_without_the_checkpoint():
    p = _p(manga_segmenter=True, weights="/nowhere/ctd.onnx")
    assert p.manga_segmenter() is False
    assert p.why_not_manga_segmenter()


def test_it_is_off_on_a_manhwa():
    """Every number came off 23 pages of Japanese, and Manga109 is manga."""
    p = _p(medium="manhwa", manga_segmenter=True, weights="/x/ctd.onnx")
    assert p.manga_segmenter() is False
    assert "manga" in p.why_not_manga_segmenter()


def test_the_clean_mask_is_still_required(tmp_path, monkeypatch):
    """The app's own folder is pointed somewhere empty on purpose: an empty
    "Model file" box now looks beside the app before giving up."""
    from mangatl import project as P
    monkeypatch.setattr(P, "__file__", str(tmp_path / "project.py"))
    p = _p(manga_segmenter=True, weights="")
    assert "comic-text-detector" in p.why_not_manga_segmenter()


def test_the_dialog_is_told_all_three_answers():
    s = _p().summary()["manga_segmenter"]
    assert set(s) == {"ready", "partly", "on", "why"}
    assert s["ready"] is False


def test_a_manhwa_is_not_offered_the_row_at_all():
    """There is nothing a manhwa could download to make this apply."""
    s = _p(medium="manhwa").summary()["manga_segmenter"]
    assert s["partly"] is False


def test_the_downloaded_filename_is_accepted():
    """Hugging Face calls it `best.pt` and that is what lands in Downloads."""
    import inspect
    src = inspect.getsource(Project.m109_weights)
    for name in ("m109seg.pt", "manga109-seg.pt", "best.pt"):
        assert name in src


def test_the_size_is_the_measured_knee():
    """640 loses a site, 1280 buys nothing, 1536 buys four for a second."""
    assert mangaseg.SIZE == 1024


def test_the_three_classes_are_named_not_numbered():
    assert (mangaseg.TEXT, mangaseg.BALLOON, mangaseg.FRAME) == \
        ("text", "balloon", "frame")


def test_panels_are_not_asked_for_by_default():
    """Nothing in the pipeline reads a panel, so it is not carried around."""
    import inspect
    sig = inspect.signature(mangaseg.read)
    assert sig.parameters["want"].default == (mangaseg.TEXT,
                                              mangaseg.BALLOON)


def test_a_missing_wheel_is_a_sentence_rather_than_a_traceback():
    """The import is TRIED here rather than left to explode at the first page.

    A traceback out of the middle of a run is not something anybody can act
    on; `ultralytics is not installed` is.
    """
    import inspect
    src = inspect.getsource(mangaseg.why_not)
    guard = src[src.index("import ultralytics"):]
    assert "    try:\n        import ultralytics" in src
    assert guard.startswith("import ultralytics")
    assert "except Exception:" in guard
    assert "ultralytics is not installed" in guard


def test_no_weights_says_so():
    assert mangaseg.why_not("") == "no Manga109 segmenter weights are set"
    assert "not at" in mangaseg.why_not("/nowhere/at/all.pt")


def test_the_balloon_share_is_of_the_writing_not_of_the_balloon():
    """A balloon is always the bigger of the two, so the question is what
    share of the WRITING is in it."""
    writing = (100, 100, 200, 300)
    balloon = (80, 80, 400, 500)
    assert dbcoo._share(writing, balloon) == 1.0
    assert dbcoo._share(balloon, writing) < dbcoo.IN_BALLOON


def test_the_balloon_bar_leaves_room_for_two_heads_disagreeing():
    """The two rectangles come off two heads of one net and their edges do
    not agree to the pixel."""
    assert 0.4 < dbcoo.IN_BALLOON < 0.9


def test_the_margins_are_filled_and_gated():
    """The segmenter's own misses are all page furniture, and the gate is the
    same bodies-of-ink bar that separates a credits strip from a hand."""
    assert dbcoo.FILL_GAPS is True
    import inspect
    src = inspect.getsource(dbcoo.detect_m109)
    assert "glyph_bodies" in src
    assert "spare" in src


def test_comic_text_detector_runs_once():
    """Its two heads are one forward pass; asking twice cost 3.6s of 14.8."""
    src = (PKG / "detect" / "dbcoo.py").read_text(encoding="utf-8")
    body = src[src.index("def detect_m109("):src.index("def _kind_family(")]
    assert body.count("CT.detect_comictext(") == 1
    assert "getattr(page, \"seg_mask\", None)" in body


def test_the_route_reads_every_switch_rather_than_its_own_numbers():
    import inspect
    sig = inspect.signature(dbcoo.detect_m109)
    assert sig.parameters["inside"].default == dbcoo.IN_BALLOON
    assert sig.parameters["fill_gaps"].default is dbcoo.FILL_GAPS
    assert sig.parameters["glyphs"].default == dbcoo.SFX_GLYPHS
    assert sig.parameters["split_sfx"].default is dbcoo.SPLIT_SFX
    assert sig.parameters["split_texts"].default is dbcoo.SPLIT_TEXTS


def test_the_settings_page_has_a_card_for_it():
    """The three routes are one card group now, not three ticks --
    see `test_stop_means_stop`. The invariant is the same: it is on
    the Settings page, it says why it cannot run, and it is drawn
    when the settings load."""
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert 'data-route="manga_segmenter"' in html
    assert 'id="routeWhy"' in html
    assert "'manga_segmenter'" in js, "the route is one the picker knows"
    assert "function syncRoutes(" in js
    assert "syncRoutes();" in js

def test_the_wheel_is_no_longer_optional_in_the_requirements():
    req = (PKG / "requirements.txt").read_text(encoding="utf-8")
    assert "ultralytics>=8.2" in req
    assert "# ultralytics>=8.2" not in req


@pytest.mark.parametrize("medium", ["manhwa", "manhua", "webtoon"])
def test_only_manga(medium):
    assert _p(medium=medium, manga_segmenter=True,
              weights="/x/ctd.onnx").manga_segmenter() is False
