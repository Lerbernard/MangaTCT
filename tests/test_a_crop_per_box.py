"""Sending a close-up of every box instead of the page.

lee: *"would it be feasible to instad of sending the pages, we send zommed
version of allthe boxes instread? hwo woud that wowrk or affct the frice?"* -
and then, given the numbers, *"yes do that"*.

MEASURED on 9 pages of his chapter 1, 20 tiles and 40 boxes, counting image
tokens the way the API does (area / 750):

    the whole page in tiles, as now        2356 tokens per page
    a crop per box, glyphs at 48 px        1027    -56%
    a crop per box, glyphs at 64 px        1554    -34%
    a crop per box, glyphs at 80 px        2230     -5%
    a crop per box, glyphs at 96 px        2971    +26%

It is CHEAPER because the hair and the sky and the trousers stop being paid
for. Page 011's name arrives at 40 px today; for less money it arrives at 64.

**Scaled by the GLYPHS, not by the crop.** Scaling each crop to a fixed long
side looks like the same thing and is not - 048's small box would go 33 px to
143 and 029's wide narration panel 33 to 44, because a wide box spreads a fixed
budget over more writing. The glyph is what decides a misread, so the glyph is
what is held constant.

**And batched.** A page becomes a dozen small pictures that all want the same
system prompt and the same region listing. Sent one at a time that text is paid
for a dozen times and the whole saving is gone, so they ride in one turn.

The cost of it, which is real: a crop shows less of the page than a tile does,
and a box drawn too tight has less to fall back on. `BOX_PAD` is that
allowance, and it is the reason page 011's dashes - which sit OUTSIDE its box -
are still in the picture.
"""
import base64

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import ocr
from mangatl.models import Page, TextRegion


def _page(boxes, glyph=20, h=1400, w=700):
    """A page with a run of writing in each of `boxes`."""
    img = np.full((h, w, 3), 245, np.uint8)
    regions = []
    for i, (x, y, bw, bh) in enumerate(boxes):
        m = np.zeros((h, w), np.uint8)
        n = max(1, bw // (glyph + 8))
        for k in range(n):
            cv2.rectangle(m, (x + 4 + k * (glyph + 8), y + 4),
                          (x + 4 + k * (glyph + 8) + glyph, y + 4 + glyph),
                          255, -1)
        img[m > 0] = 20
        r = TextRegion(id=i, bbox=(x, y, bw, bh), text_mask=m,
                       bubble_mask=None, bubble_bbox=(x, y, bw, bh),
                       kind="bubble")
        r.order = i
        regions.append(r)
    p = Page(image=img, source_path="t.png")
    p.regions = regions
    return p


def _sizes(tiles):
    out = []
    for b, ids in tiles:
        a = cv2.imdecode(np.frombuffer(b, np.uint8), 1)
        out.append((a.shape[1], a.shape[0], ids))
    return out


# ------------------------------------------------------------- what comes out

def test_one_crop_per_box():
    p = _page([(80, 100, 300, 60), (80, 700, 300, 60), (300, 1100, 200, 60)])
    tiles = ocr.page_box_crops(p)
    assert len(tiles) == 3
    assert [ids for _b, ids in tiles] == [[0], [1], [2]]


def test_a_page_with_no_boxes_sends_nothing():
    p = _page([])
    assert ocr.page_box_crops(p) == []


def test_the_crops_come_in_reading_order():
    p = _page([(80, 700, 300, 60), (80, 100, 300, 60)])
    p.regions[0].order, p.regions[1].order = 1, 0
    assert [ids[0] for _b, ids in ocr.page_box_crops(p)] == [1, 0]


def test_the_glyphs_arrive_at_the_size_asked_for():
    """The whole point. A 20px character on the page comes back near 64."""
    p = _page([(80, 100, 300, 60)], glyph=20)
    b, _ids = ocr.page_box_crops(p, glyph_px=64)[0]
    a = cv2.imdecode(np.frombuffer(b, np.uint8), 1)
    g = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    n, _l, st, _c = cv2.connectedComponentsWithStats((g < 128).astype(np.uint8), 8)
    hs = sorted(int(st[i, cv2.CC_STAT_HEIGHT]) for i in range(1, n)
                if int(st[i, cv2.CC_STAT_AREA]) >= 25)
    assert hs, "no writing in the crop at all"
    got = hs[len(hs) // 2]
    assert 48 <= got <= 88, (got, hs)


def test_a_big_box_and_a_small_one_arrive_at_the_same_glyph_size():
    """Scaling by the crop's long side would make these two wildly different -
    that is the trap this is written against."""
    p = _page([(60, 100, 560, 90)], glyph=34)
    q = _page([(60, 100, 120, 50)], glyph=14)
    out = []
    for pg in (p, q):
        b, _ids = ocr.page_box_crops(pg, glyph_px=64)[0]
        a = cv2.imdecode(np.frombuffer(b, np.uint8), 1)
        g = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
        n, _l, st, _c = cv2.connectedComponentsWithStats(
            (g < 128).astype(np.uint8), 8)
        hs = sorted(int(st[i, cv2.CC_STAT_HEIGHT]) for i in range(1, n)
                    if int(st[i, cv2.CC_STAT_AREA]) >= 25)
        out.append(hs[len(hs) // 2] if hs else 0)
    assert abs(out[0] - out[1]) <= 20, out


def test_the_crop_carries_the_page_around_the_box():
    """`BOX_PAD` - and it is not cosmetic. Page 011's dashes sit OUTSIDE its
    box, and a hard crop is how they would be lost for a second time."""
    p = _page([(200, 400, 200, 60)])
    b, _ids = ocr.page_box_crops(p, glyph_px=20)[0]
    a = cv2.imdecode(np.frombuffer(b, np.uint8), 1)
    assert a.shape[1] > 200 and a.shape[0] > 60
    assert ocr.BOX_PAD > 0


def test_nothing_is_bigger_than_the_api_takes():
    p = _page([(20, 20, 660, 900)], glyph=8)
    for b, _ids in ocr.page_box_crops(p, glyph_px=96):
        a = cv2.imdecode(np.frombuffer(b, np.uint8), 1)
        assert max(a.shape[:2]) <= ocr.MAX_SIDE, a.shape


def test_a_tiny_box_still_arrives_big_enough_to_look_at():
    """A box whose characters are ALREADY near the target barely scales at all,
    and a two-character box is then a postage stamp. `BOX_MIN` is the floor."""
    p = _page([(300, 300, 44, 36)], glyph=28)
    b, _ids = ocr.page_box_crops(p)[0]
    a = cv2.imdecode(np.frombuffer(b, np.uint8), 1)
    assert max(a.shape[:2]) >= ocr.BOX_MIN, a.shape


def test_the_default_target_is_the_measured_one():
    """Called with no argument - which is how the app calls it. 64 px is the
    row of the table that is a third cheaper than sending the page."""
    assert 48 <= ocr.BOX_GLYPH <= 80
    p = _page([(80, 100, 300, 60)], glyph=20)
    b, _ids = ocr.page_box_crops(p)[0]
    a = cv2.imdecode(np.frombuffer(b, np.uint8), 1)
    g = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    n, _l, st, _c = cv2.connectedComponentsWithStats((g < 128).astype(np.uint8), 8)
    hs = sorted(int(st[i, cv2.CC_STAT_HEIGHT]) for i in range(1, n)
                if int(st[i, cv2.CC_STAT_AREA]) >= 25)
    assert hs and 48 <= hs[len(hs) // 2] <= 88, hs


def test_it_costs_less_than_the_page_does():
    """The reason for doing it, on the shape of page it was measured on: a
    webtoon strip, mostly artwork, with ordinary-sized writing in it.

    NOT true of every page, and the test says which kind it is true of. A short
    page of very small writing goes the other way - the crops are scaled up
    several times and the page was cheap to begin with. The saving comes from
    not paying for a 690x3000 strip of hair and sky.
    """
    p = _page([(80, 300, 400, 90), (80, 1400, 400, 90), (200, 2500, 300, 90)],
              glyph=40, h=3000, w=690)
    tok = lambda ts: sum(w * h for w, h, _i in _sizes(ts)) / 750.0
    crops, tiles = tok(ocr.page_box_crops(p)), tok(ocr.page_label_tiles(p))
    assert crops < tiles, (crops, tiles)
    assert crops < 0.75 * tiles, (crops, tiles)


# ------------------------------------------------------- the setting reaches it

def test_the_reading_detail_setting_picks_it():
    p = _page([(80, 100, 300, 60), (80, 700, 300, 60)])
    assert len(ocr.page_label_tiles(p, detail="boxes")) == 2
    assert len(ocr.page_label_tiles(p, detail="auto")) == 1


def test_the_settings_page_does_not_offer_it_any_more():
    """It is not a choice: lee: *"make teh zoomed ... teh only option for the
    read text ... it sho9ud just happen in teh backgroud"*. The menu that used
    to stand here is gone, and so is every other reading-detail control."""
    from pathlib import Path
    html = (Path(ocr.__file__).parent / "static" / "editor.html").read_text(
        encoding="utf-8")
    assert 'id="ocr_detail"' not in html


# --------------------------------------------------------------- the batching

class _Client:
    """Counts turns and how many pictures rode in each."""

    def __init__(self):
        self.turns = []
        self.messages = self

    def create(self, **kw):
        imgs = [c for c in kw["messages"][0]["content"] if c["type"] == "image"]
        self.turns.append(len(imgs))
        ids = [c for c in kw["messages"][0]["content"] if c["type"] == "text"]
        import types
        body = '{"regions":[{"id":0,"text":"ok"},{"id":1,"text":"ok"},'\
               '{"id":2,"text":"ok"}]}'
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text=body)],
            usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))


def _read(tiles, batch):
    from mangatl.translate import read_page_ocr

    class Ctx:
        backend = "anthropic"; base_url = ""; model = "m"; api_key = "k"
        medium = "manhwa"; source = "Korean"; glossary = {}; characters = {}
        safety = ""; step_name = ""
    p = _page([(80, 100, 300, 60), (80, 700, 300, 60), (300, 1100, 200, 60)])
    c = _Client()
    read_page_ocr(p, Ctx(), tiles, client=c, model="m", batch=batch)
    return c.turns


def test_a_crop_per_box_is_still_one_turn():
    p = _page([(80, 100, 300, 60), (80, 700, 300, 60), (300, 1100, 200, 60)])
    tiles = ocr.page_box_crops(p)
    assert _read(tiles, batch=len(tiles)) == [3], \
        "a dozen crops must not be a dozen system prompts"


def test_without_batching_it_is_a_turn_each():
    p = _page([(80, 100, 300, 60), (80, 700, 300, 60), (300, 1100, 200, 60)])
    tiles = ocr.page_box_crops(p)
    assert _read(tiles, batch=1) == [1, 1, 1]


def test_the_reader_is_told_which_image_is_which():
    """Several pictures in one turn are useless if the model cannot say which
    answer belongs to which."""
    import mangatl.translate as T
    seen = {}
    real = T._ask_vision

    def spy(client, kind, model, system, user, image_b64, media_type="image/png"):
        seen["user"] = user
        seen["n"] = 1 if isinstance(image_b64, str) else len(image_b64)
        return '{"regions":[]}'
    T._ask_vision = spy
    try:
        p = _page([(80, 100, 300, 60), (80, 700, 300, 60)])
        tiles = ocr.page_box_crops(p)
        _read(tiles, batch=len(tiles))
    finally:
        T._ask_vision = real
    assert seen["n"] == 2
    assert "one per region" in seen["user"], seen["user"][:400]
    assert "0, 1" in seen["user"], seen["user"][:400]


# ---------------------------------------- ...and it is what the webtoons get

def test_the_webtoons_get_a_crop_per_box():
    """lee, after the four-way read: *"make teh zoom be teh default for mnahwa
    and manhua"*. It is the only mode that got page 011's name."""
    assert ocr.detail_for("manhwa") == "boxes"
    assert ocr.detail_for("manhua") == "boxes"


def test_manga_gets_a_crop_per_box_too_now_that_it_has_been_scored():
    """It used to stay on tiles because the crops had never been scored on a
    manga page. They have been: chapter 3, 23 pages, 225 boxes, read at 4
    pieces, 9 pieces and zoomed, each against manga-ocr - which reads one
    box's pixels and so cannot file an answer under the wrong number.

    4 pieces misfiled 16 boxes on 7 pages, 9 pieces misfiled 20 on 9 pages,
    and the crops misfiled 2 - both of which are two boxes that really do hold
    the same words. Cutting FINER made it worse, which says the mistake was
    never resolution: it is matching what was read to numbers drawn on a page,
    and a crop with one box in it has nothing to match."""
    assert ocr.detail_for("manga") == "boxes"
    assert ocr.detail_for("") == "boxes"
    assert ocr.detail_for(None) == "boxes"


def test_the_project_arrives_with_nothing_chosen():
    """Empty, not a word: a word here would be a second place the answer lives
    and it would go stale the day the measurement moves."""
    import inspect

    from mangatl.project import Project
    assert '"ocr_detail": "",' in inspect.getsource(Project)


def test_the_saved_key_is_kept_even_though_nothing_reads_it():
    """A project saved by an older copy of the app has a word in `ocr_detail`.
    The key stays in the sheet, empty: one that vanished would be deleted by
    the next save, and a settings file that loses keys when the app is
    upgraded is a settings file nobody can downgrade."""
    from pathlib import Path
    js = (Path(ocr.__file__).parent / "static" / "js" / "project.js").read_text(
        encoding="utf-8")
    assert "ocr_detail:''" in js
    import inspect
    from mangatl.project import Project
    assert '"ocr_detail": ""' in inspect.getsource(Project)


# ------------------------------- the setting that was measured and taken out

def test_there_is_no_resolution_toggle_left():
    """It never won. Nothing at all under a crop per box - the bytes come back
    identical - and on tiles it cost +50% and produced the worst of the four
    runs, five misreads no other run made. A setting that only has a wrong
    answer is worse than no setting."""
    import inspect
    import shutil
    from pathlib import Path

    from mangatl.project import Project
    from scratch import scratch
    root = Path(ocr.__file__).parent
    tmp = scratch("_tmp_nofill")
    shutil.rmtree(tmp, ignore_errors=True)
    assert "ocr_fill" not in Project(None, tmp).settings, \
        "a dead key still arrives on every new project and is saved forever"
    for rel in ("static/editor.html", "static/js/project.js"):
        assert "ocr_fill" not in (root / rel).read_text(encoding="utf-8"), rel
    assert "fill" not in inspect.signature(ocr.page_label_tiles).parameters
    assert "fill" not in inspect.signature(ocr._encode).parameters


def test_a_small_piece_is_sent_at_the_size_it_is():
    """`_encode` shrinks and never grows, which is what it did before the
    toggle and what it does after it."""
    p = _page([(80, 300, 400, 90)], glyph=40, h=1200, w=690)
    b, _ids = ocr.page_label_tiles(p, detail="auto")[0]
    a = cv2.imdecode(np.frombuffer(b, np.uint8), 1)
    assert max(a.shape[:2]) < ocr.MAX_SIDE


def test_a_big_piece_is_still_cut_down():
    p = _page([(80, 300, 400, 90)], glyph=40, h=4000, w=2400)
    for b, _ids in ocr.page_label_tiles(p, detail="page"):
        a = cv2.imdecode(np.frombuffer(b, np.uint8), 1)
        assert max(a.shape[:2]) == ocr.MAX_SIDE


# ------------------------------------------- ...and what the read step reads

def _run_read(settings, monkeypatch):
    """Drive `editor.do_ocr` far enough to see what it asked the cutter for.

    A stub project rather than one on disk: the question is only which
    arguments travel from the settings sheet to `page_label_tiles`, and a real
    project would drag a page file, a model and a network call in with it."""
    import types

    from mangatl import editor, ocr as O, translate as T
    seen = {}

    def spy(page, max_side=O.MAX_SIDE, detail="auto"):
        seen["detail"] = detail
        return []

    monkeypatch.setattr(O, "page_label_tiles", spy)
    monkeypatch.setattr(T, "read_page_ocr", lambda *a, **k: {})
    monkeypatch.setattr(T, "link_sections", lambda regs: None)

    r = TextRegion(id=0, bbox=(0, 0, 10, 10), text_mask=None, bubble_mask=None,
                   bubble_bbox=(0, 0, 10, 10), kind="bubble")
    page = Page(image=np.full((40, 40, 3), 245, np.uint8), regions=[r])
    ctx = types.SimpleNamespace(medium="manhwa", source="", target="en",
                                safety="", synopsis="", characters="",
                                glossary="", story="", notes="")
    p = types.SimpleNamespace(settings=dict(settings), ctx=ctx, job={},
                              materialize=lambda i: page,
                              commit=lambda i, pg: None)
    try:
        editor.do_ocr(p, 0)
    except Exception:
        # `_ctx_from_settings` may want more of a project than a stub has;
        # what is being watched happens after it either way.
        pass
    return seen


def test_a_manhwa_project_nobody_configured_reads_a_crop_per_box(monkeypatch):
    """The whole point of the change, driven through the real step."""
    assert _run_read({"medium": "manhwa"}, monkeypatch).get("detail") == "boxes"
    assert _run_read({"medium": "manhua", "ocr_detail": ""},
                     monkeypatch).get("detail") == "boxes"


def test_a_manga_project_nobody_configured_reads_a_crop_per_box_too(monkeypatch):
    """Driven through the real step, the same as the webtoon case above.
    See `detail_for` for the chapter 3 numbers that moved this."""
    assert _run_read({"medium": "manga"}, monkeypatch).get("detail") == "boxes"
    assert _run_read({}, monkeypatch).get("detail") == "boxes"


def test_an_old_saved_choice_is_not_obeyed(monkeypatch):
    """There is no menu to have chosen from any more, so a word left in the
    file is last year's answer rather than somebody's decision - and a chapter
    half-read on tiles and half on crops would be two runs under one name."""
    got = _run_read({"medium": "manhwa", "ocr_detail": "page"}, monkeypatch)
    assert got.get("detail") == "boxes"
    got = _run_read({"medium": "manga", "ocr_detail": "high"}, monkeypatch)
    assert got.get("detail") == "boxes"
