"""The checkpoints load when the card is picked, not on page one.

lee timed three of the four cards and got 50, 58 and 60 seconds a page against
estimates of 2.94, 9.9 and 12.7. Measured in a fresh process, three pages:

    comic-text-detector    page 1   9.54s   page 2   4.77s   page 3   4.48s
    DB++ / COO             page 1  54.28s   page 2  14.10s   page 3   9.63s
    Manga109 YOLO26        page 1  30.54s   page 2  13.72s   page 3  13.71s

Not one route was slow. The models load on whichever page happens to be first
- the 116MB sound-effect checkpoint, the torch import, ultralytics - and the
bar spends that whole time reading "Detecting... 0 of 30". A fifteen-second
load told as a fifty-second page, and lee drew that conclusion three times,
once per card.

So two changes, and the second is the one that matters.

**The loading moves to the moment the card is picked**, where there is nothing
to misread it as. The run warms too, because a chapter opened straight into
Find text has picked nothing this session.

**The bar says which model.** "Loading DB++ / COO" instead of a page count for
a page that has not started. Moving the wait without saying so would just move
where the wrong conclusion gets drawn.
"""
import pytest

from where import PKG


# ------------------------------------------------- what warming actually does

def test_it_loads_what_the_picked_route_needs_and_nothing_else(tmp_path,
                                                               monkeypatch):
    """The plain card must not drag in the 116MB sound-effect checkpoint, and
    a route that IS picked must not be left to load it on page one."""
    from mangatl import project as P
    from mangatl.project import Project

    asked = []

    ctd = tmp_path / "comictextdetector.pt.onnx"
    ctd.write_bytes(b"x")
    (tmp_path / "dbpp_coo.dat").write_bytes(b"x")
    (tmp_path / "animetext.pt").write_bytes(b"x")
    monkeypatch.setattr(P, "__file__", str(tmp_path / "project.py"))

    from mangatl.detect import comictext as CT
    from mangatl.detect import animetext as AT
    from mangatl.detect import onomatopoeia as OO
    monkeypatch.setattr(CT, "_get_net", lambda path: None)
    monkeypatch.setattr(CT, "page_text_mask", lambda i, w: asked.append("ctd"))
    monkeypatch.setattr(AT, "why_not", lambda p: "")
    monkeypatch.setattr(AT, "pieces", lambda i, c: asked.append("animetext"))
    monkeypatch.setattr(OO, "why_not", lambda p: "")
    monkeypatch.setattr(OO, "pieces", lambda i, c: asked.append("coo"))

    p = Project(None, str(tmp_path / "out"))
    p.settings["medium"] = "manga"

    # AnimeText is the DEFAULT route now - lee: *"make anime text teh default
    # detector"* - so a project nobody configured warms all three.
    assert p.warm_models() == "AnimeText YOLO12-L"
    assert asked == ["ctd", "animetext", "coo"], asked

    # ...and the plain card, chosen, is comic-text-detector and no more.
    asked.clear()
    p.settings["animetext"] = False
    p.warm_models()
    assert asked == ["ctd"], asked


def test_a_checkpoint_that_is_not_there_is_not_an_error(tmp_path, monkeypatch):
    """Picking a card must not raise. Every one of these paths is asked again
    properly, with a sentence somebody can act on, by `why_not`."""
    from mangatl import project as P
    from mangatl.project import Project

    monkeypatch.setattr(P, "__file__", str(tmp_path / "project.py"))
    p = Project(None, str(tmp_path / "out"))
    p.settings.update(medium="manga", manga_segmenter=True, animetext=False)
    assert p.warm_models() == "Manga109 YOLO26"      # no weights anywhere


def test_the_route_is_named_in_the_words_on_the_card():
    """A message naming a route by its settings key is a message nobody can
    match to the button they clicked."""
    from mangatl.project import Project
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    for _, name in Project.ROUTE_NAMES:
        assert ">%s<" % name.replace("&", "&amp;") in html \
            or name in html, name


# ------------------------------------------------- when it happens

def test_picking_a_card_starts_the_loading():
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    body = js.split("function pickRoute(", 1)[1].split("\nfunction ", 1)[0]
    assert "/api/models/warm" in body
    assert body.index("saveSettings()") < body.index("/api/models/warm"), \
        "the choice is saved before anything acts on it"


def test_a_run_waits_for_the_load_rather_than_racing_it():
    """Two threads reading the same 116MB checkpoint at once both do it - the
    caches these fill are plain dicts with no lock. Picking a card and pressing
    Find text a second later is the obvious way to use this, not a rare one."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def _run_one("):src.index("def _dispatch(")]
    assert 'warm_models(p, wait=True)' in body
    at = body.index("warm_models(p, wait=True)")
    assert at < body.index("for n, i in enumerate(indices, 1):"), \
        "before the pages, not beside them"
    warm = src[src.index("def warm_models("):src.index("def _hosted_cleaning(")]
    assert "t.join()" in warm
    assert "not t.is_alive()" in warm, "a live loader is joined, not duplicated"


def test_the_detect_run_is_the_one_that_warms():
    """Its own argument on the queue item, and NOT a value of `step`.

    `step` is the PRICE - one of `PAID_STEPS`, or empty for the runs that cost
    nothing - and `test_the_ai_find_pass_is_gone` holds Find text to having no
    price at all by refusing to see `step=` anywhere in that branch. Hanging a
    second meaning on it made a free run look chargeable to the one test
    guarding that it is free.
    """
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    assert 'lambda i: p.detect(i, kinds, nobig), warm=True)' in src
    body = src[src.index("def _run_one("):src.index("def _dispatch(")]
    assert 'if item.get("warm"):' in body
    # ...and the flag reaches the runner rather than being dropped on the queue.
    q = src[src.index("def run_job("):]
    assert '"warm": warm' in q[:q.index("\ndef ")]


def test_finding_text_is_still_free():
    """The guard this was nearly broken by, asked here too so the next person
    to want a per-run flag reads it in the file that wanted one."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    i = src.index('if path == "/api/detect_all":')
    branch = src[i:src.index("if path ==", i + 10)]
    assert "step=" not in branch, branch


# ------------------------------------------------- and what it says while it does

def test_the_bar_says_which_model_instead_of_counting_a_page():
    js = (PKG / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")
    assert "j.loading_model" in js
    assert "`Loading ${j.loading_model}…`" in js
    at = js.index("j.loading_model")
    tail = js[at:at + 400]
    assert "${j.done} of ${j.total}" in tail, \
        "the page count is the OTHER branch, not gone"
    # (It used to read "9 of 23 pages (39%)". The bar carries its own words
    #  now, so the percentage has a slot on the right of it and the word
    #  "pages" came out with it. See `test_the_bar_says_it_on_itself`.)


def test_the_server_sends_it_only_while_it_is_true():
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    at = src.index('if path == "/api/job":')
    body = src[at:at + 900]
    assert 'if _models["running"]:' in body
    assert 'j["loading_model"] = _models["route"]' in body


def test_a_blank_page_goes_through_each_net_not_just_the_file(tmp_path,
                                                              monkeypatch):
    """Loading the checkpoint is only half of it.

    Measured on DB++/COO, one fresh process, three pages:

        no warming at all      page 1  54.28s   page 3   9.63s
        checkpoints loaded     page 1  20.06s   page 3   9.24s
        ...and one blank pass  page 1  13.45s   page 3   8.97s

    More than half of what the load left behind is the FIRST forward pass -
    torch picking kernels, OpenCV laying out layers, allocators sizing
    themselves. None of it cares what is in the image, so it happens here on
    256 pixels of white rather than on page one of somebody's chapter.
    """
    import numpy as np
    from mangatl import project as P
    from mangatl.project import Project
    from mangatl.detect import comictext as CT

    seen = {}
    ctd = tmp_path / "comictextdetector.pt.onnx"
    ctd.write_bytes(b"x")
    monkeypatch.setattr(P, "__file__", str(tmp_path / "project.py"))
    monkeypatch.setattr(CT, "_get_net", lambda path: None)
    monkeypatch.setattr(CT, "page_text_mask",
                        lambda img, w: seen.update(shape=img.shape,
                                                   ink=int(img.min())))

    p = Project(None, str(tmp_path / "out"))
    p.settings["medium"] = "manga"
    p.warm_models()
    assert seen["shape"] == (Project.WARM_SIDE, Project.WARM_SIDE, 3)
    assert seen["ink"] == 255, "blank, so nothing downstream finds work to do"
    assert Project.WARM_SIDE < 512, "small: the pass existing is what is paid for"


def test_the_endpoint_answers_without_waiting_for_the_read():
    """A settings page that blocks on a 116MB file to register a click is the
    same wait in a worse place."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    at = src.index('if path == "/api/models/warm":')
    body = src[at:at + 1100]
    assert "warm_models(p)" in body and "wait=True" not in body
    assert '"route": p.route_name()' in body


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
