"""Reading the text out of each region.

Two engines, because no single one covers every language well:

  manga-ocr   Japanese only. A ViT encoder-decoder fine-tuned on manga. Reads
              vertical and horizontal text without being told which, copes
              with stylised fonts, and was trained with furigana present so it
              mostly ignores ruby rather than interleaving it. Far and away
              the best option for manga, and useless for anything else.

  easyocr     Korean, Chinese, Japanese and many more. General-purpose, so
              weaker on stylised comic typesetting, but it is what makes manhwa
              and manhua work at all. Text in those is usually horizontal,
              which suits it.

Pick with the `engine` argument, or leave it on "auto" to choose by language.
"""
from __future__ import annotations

import re
import unicodedata

import cv2
import numpy as np
from PIL import Image

from . import kinds as _kinds
from . import stopping as _stopping
from .models import Page, TextRegion

MIN_SHORT_SIDE = 64     # model degrades badly on tiny crops
PAD = 4
# Below this many inked pixels there is no shape to measure - a speck of dust,
# the tail of a neighbour's glyph - and the box itself is the better answer.
MIN_INK = 12
# How far outside the ink the outline is drawn. The line is 2px thick and it
# is drawn ON the page the reader is sent, so it must clear the glyphs.
GROW = 4

# language code -> engine that can actually read it
LANG_ENGINE = {"ja": "manga-ocr", "ko": "easyocr", "zh": "easyocr",
               "en": "easyocr"}
EASY_CODES = {"ja": "ja", "ko": "ko", "zh": "ch_sim", "en": "en",
              "es": "es", "pt": "pt", "fr": "fr"}

_engines: dict = {}


# The engines that exist. A name that is not one of these is not a choice,
# whatever a settings file says.
ENGINES = ("manga-ocr", "easyocr")


def choose_engine(lang: str = "ja", engine: str = "auto") -> str:
    """Which offline engine reads this language.

    Anything that is not the name of a real engine means "decide for me". It
    has to, because projects on disk carry `ocr_engine: "ai"` - the editor
    saved that string for a menu that no longer exists, and taken literally it
    sent Japanese pages to easyocr, which reads a manga balloon as `多つ こ 鼻`.
    """
    if engine and engine in ENGINES:
        return engine
    return LANG_ENGINE.get(lang, "easyocr")


class _MangaOcr:
    """Japanese only."""

    def __init__(self):
        from manga_ocr import MangaOcr
        self.m = MangaOcr()

    def __call__(self, pil_image) -> str:
        return self.m(pil_image)

    def batch(self, pil_images) -> list[str]:
        """Run several crops through the model in one go.

        One forward pass over N images beats N passes over one: the CPU's
        matrix units actually get fed. Reaches into manga_ocr's internals,
        so any surprise drops back to the safe one-at-a-time path.
        """
        if len(pil_images) < 2:
            return [self(i) for i in pil_images]
        m = self.m
        model = getattr(m, "model", None)
        proc = (getattr(m, "processor", None)
                or getattr(m, "feature_extractor", None))
        tok = getattr(m, "tokenizer", None) or getattr(proc, "tokenizer", None)
        if not (model is not None and proc is not None and tok is not None):
            return [self(i) for i in pil_images]
        try:
            import torch
            try:
                from manga_ocr.ocr import post_process
            except Exception:
                def post_process(t):           # what manga_ocr does, roughly
                    return "".join(t.split())
            ims = [im.convert("L").convert("RGB") for im in pil_images]
            px = proc(images=ims, return_tensors="pt").pixel_values
            with torch.inference_mode():
                out = model.generate(px, max_length=300)
            return [post_process(tok.decode(seq, skip_special_tokens=True))
                    for seq in out]
        except Exception:
            return [self(i) for i in pil_images]


class _EasyOcr:
    """Multi-language. Slower and less comic-savvy, but reads Korean and
    Chinese, which manga-ocr cannot."""

    def __init__(self, lang: str):
        import easyocr
        code = EASY_CODES.get(lang, "en")
        # easyocr wants English alongside CJK for mixed typesetting
        langs = [code] if code == "en" else [code, "en"]
        self.r = easyocr.Reader(langs, gpu=False, verbose=False)

    def __call__(self, pil_image) -> str:
        import numpy as np
        parts = self.r.readtext(np.array(pil_image), detail=0, paragraph=True)
        return " ".join(p.strip() for p in parts if p.strip())


def get_engine(lang: str = "ja", engine: str = "auto"):
    name = choose_engine(lang, engine)
    key = f"{name}:{lang}"
    if key not in _engines:
        try:
            if name == "manga-ocr":
                if lang != "ja":
                    raise RuntimeError(
                        "manga-ocr only reads Japanese. Switch the OCR engine "
                        "to easyocr for Korean or Chinese.")
                _engines[key] = _MangaOcr()
            else:
                _engines[key] = _EasyOcr(lang)
        except ImportError as e:
            need = "manga-ocr" if name == "manga-ocr" else "easyocr"
            raise RuntimeError(
                f"the {name} engine is not installed: pip install {need}") from e
    return _engines[key]


def _pixel_owner(page: Page):
    """Assign every inked pixel to exactly ONE region.

    Two overlapping boxes would otherwise read the glyphs in their shared area
    twice - the same text OCR'd and translated in both. Each pixel goes to the
    region whose centre is nearest (among the regions that actually cover it),
    so a glyph belongs to a single bubble. Returns (owner, id->index): owner is
    an int map, -1 where no region, else the owning region's index.
    """
    regs = [r for r in page.regions if r.text_mask is not None]
    H, W = page.image.shape[:2]
    owner = np.full((H, W), -1, np.int32)
    if not regs:
        return owner, {}
    cover = np.zeros((H, W), np.uint16)
    for j, r in enumerate(regs):
        ink = r.text_mask > 0
        owner[ink] = j
        cover[ink] += 1
    shared = cover > 1
    if shared.any():
        ys, xs = np.nonzero(shared)
        C = np.array([[r.cx, r.cy] for r in regs], np.float32)
        P = np.stack([xs, ys], 1).astype(np.float32)
        memb = np.stack([(r.text_mask[ys, xs] > 0) for r in regs], 1)
        d = ((P[:, None, :] - C[None, :, :]) ** 2).sum(2)
        d[~memb] = np.inf
        owner[ys, xs] = d.argmin(1).astype(np.int32)
    return owner, {r.id: j for j, r in enumerate(regs)}


def ink_outline(region: TextRegion, owner: np.ndarray | None = None,
                index: int = -1) -> np.ndarray | None:
    """The turned rectangle that holds this region's own ink, in page pixels.

    A box is a rectangle, and a rectangle drawn round a sound effect running
    diagonally across a panel reaches halfway into the balloon beside it. The
    reader is then shown two rectangles lying on top of one another and asked
    which of them the words in the overlap belong to - which is not a question
    a picture of two rectangles can answer. lee: *"teh two boxes are
    overlapping on eacher text and messing teh readding"*.

    The INK answers it. Outlining the pixels each region OWNS turns the sound
    effect into a slanted strip and the speech beside it into an upright block,
    and the two barely touch. The shapes on the page then say which words go
    with which number, and neither box has to be moved to make it true.

    Upright text is unaffected: the smallest turned rectangle round a block of
    vertical columns is the block, which is the box it already had.

    Comes back None when there is nothing to measure - a box drawn on blank
    artwork, a region loaded from a project saved before masks existed - and
    the caller falls back to the rectangle, which is all it ever had.
    """
    m = getattr(region, "text_mask", None)
    if m is None:
        return None
    H, W = m.shape[:2]
    x, y, w, h = [int(v) for v in (region.bbox or (0, 0, 0, 0))]
    # Only the box's own neighbourhood is looked at: a text mask is page-sized
    # and a chapter has sixty of them.
    x0, y0 = max(0, x - PAD), max(0, y - PAD)
    x1, y1 = min(W, x + w + PAD), min(H, y + h + PAD)
    if x1 <= x0 or y1 <= y0:
        return None
    sub = m[y0:y1, x0:x1] > 0
    if owner is not None and index >= 0:
        sub = sub & (owner[y0:y1, x0:x1] == index)
    ys, xs = np.nonzero(sub)
    if len(xs) < MIN_INK:
        return None
    pts = np.stack([xs + x0, ys + y0], 1).astype(np.float32)
    (cx, cy), (rw, rh), ang = cv2.minAreaRect(pts)
    # Held off the ink by `GROW`, because the outline is DRAWN, two pixels
    # thick, onto the picture the reader gets. A box border lying along the
    # edge of the words it points at takes the top off them: in lee's panel
    # the old rectangle's bottom edge ran straight through 見, between the 目
    # and the rest, and 悪女 came back as 悪魔.
    return cv2.boxPoints(((cx, cy), (rw + GROW * 2, rh + GROW * 2), ang)
                         ).astype(np.int32)


def prepare_crop(img: np.ndarray, region: TextRegion,
                 owner: np.ndarray | None = None, my_index: int = -1
                 ) -> Image.Image:
    """Crop to the TEXT box (not the bubble), pad, upscale small crops.

    When `owner` is supplied, glyphs the crop happens to include that belong to
    a DIFFERENT region (an overlapping neighbour) are blanked to white, so this
    region is read on its own text only.
    """
    x, y, w, h = region.bbox
    H, W = img.shape[:2]
    x0, y0 = max(0, x - PAD), max(0, y - PAD)
    x1, y1 = min(W, x + w + PAD), min(H, y + h + PAD)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return Image.new("RGB", (MIN_SHORT_SIDE, MIN_SHORT_SIDE), "white")
    if owner is not None and my_index >= 0:
        sub = owner[y0:y1, x0:x1]
        other = (sub >= 0) & (sub != my_index)
        if other.any():
            crop = crop.copy()
            crop[other] = 255
    short = min(crop.shape[:2])
    if short < MIN_SHORT_SIDE:
        s = MIN_SHORT_SIDE / short
        crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    return Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))


MAX_SIDE = 1568          # what the vision APIs downscale to anyway
# How many tiles a page may be cut into, per detail setting. "page" is the old
# behaviour: one image, and a tall page loses most of its resolution to it.
TILE_BUDGET = {"page": 1, "auto": 4, "high": 9}


# How far the outline is pushed OFF the writing it names.
#
# It used to be drawn exactly on the shape, and a shape is drawn round the ink
# the detector found -- so anything the detector's box missed by a few pixels
# ended up UNDER the red line. Page 011's name card is the case: its dashes sit
# at x 280 and x 625, the box runs 290 to 617, and both dashes were painted
# over and never restored, because the restore below only puts back ink the
# region OWNS. The reader could not see them, and did not transcribe them.
#
# 3 pixels, which is more than the line's own 2px width and less than the gap
# between two neighbouring balloons. The owned ink is still repainted on top
# afterwards, so where an outset line does stray onto a neighbour's words the
# words win, exactly as before.
OUTSET = 3


def _outset(pts: np.ndarray, px: int = OUTSET) -> np.ndarray:
    """The same polygon, pushed `px` outwards from its own middle."""
    p = np.asarray(pts, np.float64)
    if len(p) < 3:
        return np.asarray(pts, np.int32)
    c = p.mean(axis=0)
    d = p - c
    n = np.hypot(d[:, 0], d[:, 1])
    n[n < 1e-6] = 1e-6
    return np.round(c + d * ((n + px) / n)[:, None]).astype(np.int32)


def _shape(r, ox: int, oy: int, outline: np.ndarray | None) -> np.ndarray:
    """The region's shape in tile coordinates: its ink's outline, or its box.

    `outline` is what the region's own ink makes (see `ink_outline`). It stands
    in for the rectangle wherever there is one, because a rectangle round
    slanted text covers everything beside it and says nothing true about which
    words are in it. Without one the rectangle is used, as it always was.
    """
    if outline is not None and len(outline) >= 3:
        return np.asarray(outline, np.int32) - np.array([ox, oy], np.int32)
    x, y, w, h = r.bbox
    x, y = x - ox, y - oy
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], np.int32)


def _draw_label(vis, r, ox: int, oy: int, tag_it: bool,
                outline: np.ndarray | None = None) -> None:
    """Outline one region on `vis`, whose top-left corner is page (ox, oy).

    A tagged region is the one being asked for - red outline, red number beside
    it. An untagged one is a neighbour that merely overlaps this crop: drawn
    grey and unnumbered, so the model can see that text belongs to somebody
    else.
    """
    pts = _shape(r, ox, oy, outline)
    cv2.polylines(vis, [_outset(pts)], True,
                  (0, 0, 255) if tag_it else (168, 168, 168), 2)
    if tag_it:
        _draw_tag(vis, r, pts)


def _draw_tag(vis, r, pts: np.ndarray) -> None:
    tag = str(r.id)
    (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    bw, bh = tw + 6, th + 6
    tx, ty = _tag_spot(vis, pts, bw, bh)
    cv2.rectangle(vis, (tx, ty), (tx + bw, ty + bh), (0, 0, 255), -1)
    cv2.putText(vis, tag, (tx + 3, ty + th + 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)


def _tag_spot(vis, pts: np.ndarray, bw: int, bh: int) -> tuple[int, int]:
    """Where to print the number: the corner of the shape covering least ink.

    Each corner is nudged outwards from the shape's middle and the paper under
    it is looked at; the emptiest wins. A number printed over a glyph costs the
    reader that glyph, and it used to be printed above the top-left corner of a
    rectangle - which, once the shape is a slanted strip, is not even near the
    words it names, and on a page of overlapping boxes was frequently sitting
    on the NEIGHBOUR'S text. Ties go to the highest corner, which is where a
    label belongs when nothing else decides it.
    """
    H, W = vis.shape[:2]
    cx, cy = float(pts[:, 0].mean()), float(pts[:, 1].mean())
    best, score = (0, 0), None
    for px, py in pts:
        dx, dy = float(px) - cx, float(py) - cy
        n = max(1.0, (dx * dx + dy * dy) ** 0.5)
        ax = int(px + dx / n * bw * 0.7) - bw // 2
        ay = int(py + dy / n * bh) - bh // 2
        ax = max(0, min(ax, max(0, W - bw)))
        ay = max(0, min(ay, max(0, H - bh)))
        patch = vis[ay:ay + bh, ax:ax + bw]
        # darkness first, height second: (ink under the tag, how far down it is)
        s = (float(255 - patch.mean()) if patch.size else 1e9, ay)
        if score is None or s < score:
            best, score = (ax, ay), s
    return best


def _encode(vis, max_side: int) -> bytes:
    """PNG, at most `max_side` on its long edge.

    There WAS a `fill` here, and a setting for it: a 690-wide webtoon tile went
    to a reader that accepts 1568 at 690, so it padded the tile up to the cap
    and spent the rest of the envelope. It is gone. Read the whole chapter four
    ways and it never won: it does nothing at all under `page_box_crops` (a
    crop is already scaled by its own characters, so the bytes come back
    identical), and on tiles it cost +50% and produced the WORST run of the
    four - five misreads no other run made. Upscaling adds no information; it
    only adds patches over a glyph, and that turned out not to be what the
    reader was short of.

    A crop per box is what buys the pixels, and it buys them at -37%.
    """
    H, W = vis.shape[:2]
    m = max(H, W)
    if m > max_side:
        s = max_side / m
        vis = cv2.resize(vis, (max(1, int(round(W * s))), max(1, int(round(H * s)))),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", vis)
    return buf.tobytes() if ok else b""


def tile_grid(H: int, W: int, max_side: int, budget: int) -> tuple[int, int]:
    """Columns and rows to cut a HxW page into so each piece keeps its pixels.

    Ideally every tile is at most `max_side` on its long edge, so nothing is
    downscaled at all. When that needs more tiles than the budget allows, drop
    whichever axis currently has the SMALLER tile dimension - growing that one
    costs the least resolution, since the other axis is what the downscale is
    measured against.
    """
    import math
    if budget <= 1:
        return 1, 1
    cols = max(1, math.ceil(W / max_side))
    rows = max(1, math.ceil(H / max_side))
    while cols * rows > budget and (cols > 1 or rows > 1):
        if cols > 1 and (rows == 1 or W / cols <= H / rows):
            cols -= 1
        elif rows > 1:
            rows -= 1
        else:
            break
    return cols, rows


def tile_rects(page: Page, max_side: int = MAX_SIDE, detail: str = "auto"
               ) -> list[tuple[tuple[int, int, int, int], list]]:
    """Where to cut the page: [((x0, y0, x1, y1), [regions])].

    Kept separate from the drawing so the geometry can be checked on its own -
    every region must land in exactly one rect, and land in it WHOLE.
    """
    img = page.image
    if img is None:
        return []
    H, W = img.shape[:2]
    regions = list(page.regions)
    if not regions:
        return []
    budget = TILE_BUDGET.get(detail or "auto", TILE_BUDGET["auto"])
    cols, rows = tile_grid(H, W, max_side, budget)
    if cols * rows <= 1:
        return [((0, 0, W, H), regions)]

    cw, ch = W / cols, H / rows
    buckets: dict[tuple[int, int], list] = {}
    for r in regions:
        c = min(cols - 1, max(0, int(r.cx // cw)))
        v = min(rows - 1, max(0, int(r.cy // ch)))
        buckets.setdefault((c, v), []).append(r)

    out = []
    # Raster order. Manga reads right-to-left, but the tiles are independent
    # requests, so order only decides how the progress count counts up.
    for v in range(rows):
        for c in range(cols):
            mine = buckets.get((c, v))
            if not mine:
                continue
            x0, y0 = int(c * cw), int(v * ch)
            x1, y1 = int((c + 1) * cw), int((v + 1) * ch)
            # Grow to hold every assigned region whole, plus a little air, so a
            # box lying across a grid line is never sliced. The grid divides up
            # the work; it is not a hard crop.
            for r in mine:
                bx, by, bw, bh = r.bbox
                x0, y0 = min(x0, bx - PAD * 4), min(y0, by - PAD * 4)
                x1, y1 = max(x1, bx + bw + PAD * 4), max(y1, by + bh + PAD * 4)
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(W, x1), min(H, y1)
            if x1 <= x0 or y1 <= y0:
                continue
            out.append(((x0, y0, x1, y1),
                        sorted(mine, key=lambda r: getattr(r, "order", 0))))
    return out


def detail_for(medium: str = "", chosen: str = "") -> str:
    """What "Reading detail" means when nobody has chosen one.

    A crop per box, on every format now. Measured twice, on two formats, and
    the crops won both.

    The webtoons first: lee's chapter 1, read four ways and scored against the
    printed pages. The crops are the only mode that got page 011's
    `하이엘프 티리스` and page 066's `드래건` - an unfamiliar string is what a
    whole-page read normalises toward something it knows, and a close-up is
    what stops it. They are also **-37%** on image tokens.

    Manga used to stay on tiles, on the honest grounds that the crops had
    never been scored on one. They have been now: chapter 3, 23 pages, 225
    boxes, read at 4 pieces, at 9 pieces and as a crop per box, each scored
    against manga-ocr - which reads the pixels inside one box and therefore
    cannot put an answer under the wrong number.

        4 pieces   83% of the dialogue agreed, 16 boxes MISFILED, 7 pages
        9 pieces   83% agreed, 20 misfiled, 9 pages
        zoomed     96% agreed, 2 misfiled - and both of those are two boxes
                   that really do hold the same words

    Cutting the page FINER made it worse, which is the tell: the mistake is
    not resolution, it is matching what was read to numbers drawn on a page.
    A crop per box has one box in it and nothing to match.

    ## ...and it is the DEAREST mode, which is what brought the choice back

    That last paragraph used to end "it is also the cheaper mode, so there is
    nothing left on the other side of the scale", and it was wrong. Measured
    over 138 real runs off lee's own ledger, a read costs about 2,400 input
    tokens PER PICTURE on the Gemini line - and zoomed sends one picture a
    box, so a ten-box page sends ten. The whole page sends one:

        1 piece    ~2,400 input tokens a page
        4 pieces   ~9,600
        9 pieces   ~21,600
        zoomed     ~2,400 x however many boxes are on the page

    On lee's chapter that is a read costing 25,000 tokens a page against the
    2,900 the price thought, which is why reading was being charged at about a
    third of what it cost. Accuracy still says zoomed and the scoring above
    still stands; what changed is that the other side of the scale turned out
    to have something on it after all. lee: *"so teh ing increasing the price
    was teh zoom in images right? if it is can you bring back teh 1, 4 and 9
    cut"*.

    So it is a CHOICE again, `boxes` is still what nobody choosing gets, and
    the price follows the choice - see `coins.usd_page`.
    """
    got = str(chosen or "").strip().lower()
    return got if got in DETAILS else "boxes"


#: The four ways the reader can be shown a page, cheapest first, with what
#: each sends. `pieces` is pictures per PAGE; `boxes` sends one a box and is
#: written as 0 because its count is not known until the page is.
DETAILS = {
    "page": {"pieces": 1, "name": "Whole page",
             "why": "One picture. The cheapest read there is, and the least "
                    "able to make out small vertical type."},
    "auto": {"pieces": 4, "name": "4 pieces",
             "why": "Quartered, so each piece arrives near its own "
                    "resolution."},
    "high": {"pieces": 9, "name": "9 pieces",
             "why": "Finer still. Scored no better than 4 on lee's chapter "
                    "and costs over twice as much."},
    "boxes": {"pieces": 0, "name": "Zoomed per box",
              "why": "A close-up of every box. The most accurate by a wide "
                     "margin - 96% against 83% - and the dearest, because it "
                     "sends one picture a box instead of one a page."},
}


def page_label_tiles(page: Page, max_side: int = MAX_SIDE, detail: str = "auto",
                     ) -> list[tuple[bytes, list[int]]]:
    """The page cut into pieces for the vision reader: [(png bytes, [region ids])].

    One 3000px page squashed to 1568 leaves small vertical typesetting a few
    pixels per glyph wide, which is where the reader starts inventing kanji.
    Cutting the page into a grid first means each piece arrives at something
    close to its native resolution.

    Every region is assigned to exactly ONE tile - the one its centre falls in -
    so nothing is read twice. The tile is then GROWN to contain each of its
    regions whole, so a box straddling a grid line is never cut in half; the
    grid is only a way of dividing up the work, not a hard crop.
    """
    if detail == "boxes":
        return page_box_crops(page, max_side=max_side)
    img = page.image
    if img is None:
        return []
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    rects = tile_rects(page, max_side, detail)
    regions = list(page.regions)
    # Each region is outlined by the ink it OWNS, so two boxes that overlap are
    # still two separate shapes on the picture the reader gets. Shared pixels
    # are settled once, here, rather than by whichever box is drawn last.
    owner, index_of = _pixel_owner(page)
    shapes = {r.id: ink_outline(r, owner, index_of.get(r.id, -1))
              for r in regions}
    out: list[tuple[bytes, list[int]]] = []
    for (x0, y0, x1, y1), mine in rects:
        vis = img[y0:y1, x0:x1].copy()
        ids = {r.id for r in mine}
        here = [r for r in regions
                if not (r.bbox[0] + r.bbox[2] <= x0 or r.bbox[0] >= x1
                        or r.bbox[1] + r.bbox[3] <= y0 or r.bbox[1] >= y1)]
        for r in here:
            cv2.polylines(vis, [_outset(_shape(r, x0, y0, shapes.get(r.id)))],
                          True,
                          (0, 0, 255) if r.id in ids else (168, 168, 168), 2)
        # The WORDS go back in front of the lines. Two boxes that sit beside
        # each other have a border between them, and it lands on whichever of
        # them is nearer - on lee's panel, box 12's edge fell across 悪, which
        # came back 悪魔 on one run and 聖女 on the next. A box is an
        # annotation; the glyph underneath it is the only thing on the page
        # that is being asked about, and nothing gets to cover it.
        keep = owner[y0:y1, x0:x1] >= 0
        if keep.any():
            vis[keep] = img[y0:y1, x0:x1][keep]
        # Numbers last, so they are not painted out by the line above.
        for r in here:
            if r.id in ids:
                _draw_tag(vis, r, _shape(r, x0, y0, shapes.get(r.id)))
        out.append((_encode(vis, max_side), [r.id for r in mine]))
    return out


# ONE CROP PER BOX, instead of the page.
#
# lee: *"would it be feasible to instad of sending the pages, we send zommed
# version of allthe boxes instread? hwo woud that wowrk or affct the frice?"*
#
# MEASURED on 9 pages of his chapter 1 -- 20 tiles, 40 boxes -- counting image
# tokens as area/750:
#
#   the whole page in tiles, as now         2356 tokens per page
#   one crop per box, glyphs at 48 px       1027    -56%
#   one crop per box, glyphs at 64 px       1554    -34%
#   one crop per box, glyphs at 80 px       2230     -5%
#   one crop per box, glyphs at 96 px       2971    +26%
#
# Cheaper, because the hair and the sky and the trousers stop being paid for.
# His 011 name arrives at 40 px today; at the same money it would arrive at 80.
#
# SCALED BY THE GLYPHS AND NOT BY THE CROP. Scaling each crop to a fixed long
# side looks equivalent and is not: 048's small box would go from 33 px to 143
# and 029's big narration panel from 33 to 44, because a wide box spreads a
# fixed budget over more writing. The glyph is the thing that decides a
# misread, so the glyph is what is held constant.
#
# The padding is not decoration. A crop is only as good as the box, and a box
# is sometimes a few pixels too tight -- page 011's dashes sit OUTSIDE its box.
# A page tile still shows what is just beyond; a hard crop does not.
BOX_GLYPH = 64          # how tall a character should arrive
BOX_PAD = 0.25          # ...with this much of the box again around it
BOX_MIN = 160           # a tiny box still needs enough picture to look at


def _glyph_px(page: Page, r) -> float:
    """How tall this box's characters are on the page, in pixels."""
    m = getattr(r, "text_mask", None)
    x, y, w, h = [int(v) for v in r.bbox]
    if m is None:
        return max(1.0, h / 3.0)
    a = np.asarray(m)
    if a.shape[:2] != page.image.shape[:2]:
        return max(1.0, h / 3.0)
    sub = (a[max(0, y):y + h, max(0, x):x + w] > 0).astype(np.uint8)
    if not sub.any():
        return max(1.0, h / 3.0)
    n, _l, st, _c = cv2.connectedComponentsWithStats(sub, 8)
    hs = [int(st[i, cv2.CC_STAT_HEIGHT]) for i in range(1, n)
          if int(st[i, cv2.CC_STAT_AREA]) >= 25]
    if not hs:
        return max(1.0, h / 3.0)
    med = float(np.median(hs))
    hs = [v for v in hs if v >= 0.45 * med] or hs
    return max(1.0, float(np.median(hs)))


def page_box_crops(page: Page, glyph_px: int = BOX_GLYPH,
                   pad: float = BOX_PAD, max_side: int = MAX_SIDE
                   ) -> list[tuple[bytes, list[int]]]:
    """Every region as its own crop, blown up so its characters are readable.

    Same annotation as the tiles: the region outlined in red and numbered, its
    neighbours outlined grey, and every region's own ink repainted over the
    lines so nothing is hidden by them.
    """
    img = page.image
    if img is None:
        return []
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    H, W = img.shape[:2]
    regions = list(page.regions)
    if not regions:
        return []
    owner, index_of = _pixel_owner(page)
    shapes = {r.id: ink_outline(r, owner, index_of.get(r.id, -1))
              for r in regions}
    out: list[tuple[bytes, list[int]]] = []
    for r in sorted(regions, key=lambda r: (getattr(r, "order", 0), r.id)):
        x, y, w, h = [int(v) for v in r.bbox]
        mx, my = int(round(pad * w)), int(round(pad * h))
        x0, y0 = max(0, x - mx), max(0, y - my)
        x1, y1 = min(W, x + w + mx), min(H, y + h + my)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        vis = img[y0:y1, x0:x1].copy()
        here = [q for q in regions
                if not (q.bbox[0] + q.bbox[2] <= x0 or q.bbox[0] >= x1
                        or q.bbox[1] + q.bbox[3] <= y0 or q.bbox[1] >= y1)]
        for q in here:
            cv2.polylines(vis, [_outset(_shape(q, x0, y0, shapes.get(q.id)))],
                          True,
                          (0, 0, 255) if q.id == r.id else (168, 168, 168), 2)
        # EVERY OWNED PIXEL GOES BACK, whoever owns it.
        #
        # Blanking the neighbour's ink was tried here for exactly one run.
        # `_pixel_owner` splits a SHARED glyph between two boxes by whichever
        # centre is nearer, which is right when two rectangles overlap and
        # their writing does not - and butchers the case it was tried for,
        # where both boxes sit on the same column of text: half of each
        # character was erased in each crop and both boxes came back holding
        # a mangled line. The before/after is in the session notes.
        #
        # The reason this line is here in the first place stands: a box is an
        # annotation, the glyph underneath is the only thing being asked
        # about, and nothing gets to cover it. Reading one line into two boxes
        # is answered in the PROMPT instead - see `build_ocr_system`.
        keep = owner[y0:y1, x0:x1] >= 0
        if keep.any():
            vis[keep] = img[y0:y1, x0:x1][keep]
        for q in here:
            if q.id == r.id:
                _draw_tag(vis, q, _shape(q, x0, y0, shapes.get(q.id)))
        # ...and now the only thing that makes this worth doing.
        s = float(glyph_px) / _glyph_px(page, r)
        ch, cw = vis.shape[:2]
        s = max(s, BOX_MIN / max(1, max(cw, ch)))
        s = min(s, max_side / max(1, max(cw, ch)))
        if abs(s - 1.0) > 0.02:
            vis = cv2.resize(vis, (max(1, int(round(cw * s))),
                                   max(1, int(round(ch * s)))),
                             interpolation=(cv2.INTER_CUBIC if s > 1
                                            else cv2.INTER_AREA))
        out.append((_encode(vis, max_side), [r.id]))
    return out


def page_label_png(page: Page, max_side: int = MAX_SIDE) -> bytes:
    """The whole page, outlined and numbered, as one PNG. The single-tile case."""
    tiles = page_label_tiles(page, max_side, detail="page")
    return tiles[0][0] if tiles else b""


def only_symbols(text: str) -> bool:
    """Is there no WRITING in this, only marks?

    lee: *"auto emove boxes taht are only symbol like ! or ....... etc"*. The
    reader finds plenty of these - a lone `!`, a row of dots trailing off, a
    `?!`, a heart - because the detector found ink there and ink is what it
    was looking for. There is nothing to translate in any of them, and every
    one costs a line of the translator's attention and a box on the page.

    Asked of Unicode's own answer rather than a list of characters somebody
    typed out. A hand-written class is a list of the marks whoever wrote it
    happened to think of: the old one here had `…` and `・` and missed `♡`,
    `★`, `※` and every full-width bracket. A character counts as WRITING when
    Unicode calls it a letter or a number - which is every script at once,
    Hangul and kana and Cyrillic included, with no list to keep up to date.

    Two deliberate exclusions from "letter":

    * Modifier letters (`Lm`) - `ー`, `々`, `ゝ`. Unicode calls them letters
      and inside a word they are, but a box holding nothing BUT them is a
      stretched sound, not a word. `ラーメン` still reads as writing; `ーー`
      does not.
    * Digits are NOT excluded. `3` on a sign, a year, a door number: that is
      something to read, and something the typesetter may have to set again.

    Empty is not symbols-only. Nothing was read at all, which is a different
    fault with a different name, and deleting a box because the reader had a
    bad turn is the one outcome this must never have.
    """
    t = (text or "").strip()
    if not t:
        return False
    for ch in t:
        cat = unicodedata.category(ch)
        if (cat[0] == "L" and cat != "Lm") or cat[0] == "N":
            return False
    return True


def looks_like_garbage(text: str, region: TextRegion) -> str | None:
    """Cheap gate. Better a flagged region than nonsense entering translation.

    Tuned for the vision reader, which reads the whole page at once (it does not
    "run away" like a per-crop decoder) and returns text with \\n line breaks.
    So length is measured on VISIBLE characters only - line breaks must not
    count - and the size test is deliberately loose: it exists only to catch a
    true runaway, never to second-guess a dense small-font bubble the model
    read correctly."""
    t = text.strip()
    if not t:
        return "ocr: empty"
    visible = re.sub(r"\s+", "", t)          # drop the model's line-break \n
    if not visible:
        return "ocr: empty"
    # The same question the "delete symbol-only boxes" switch asks, asked once
    # and in one place. This one only FLAGS - the switch is what removes the
    # box - so with the switch off a `!!` still arrives marked for review
    # rather than sliding into the translation unremarked.
    if only_symbols(visible):
        return "ocr: punctuation only"
    if re.search(r"(.)\1{6,}", visible):
        return "ocr: repeated character run"
    # Only a genuine runaway trips this: FAR more glyphs than the inked area
    # could hold, and a long string. A normal bubble never reaches it.
    ink = int((region.text_mask > 0).sum()) if region.text_mask is not None else 0
    if ink and len(visible) > 30 and len(visible) > ink / 12:
        return "ocr: implausible length for region size"
    return None


def ocr_page(page: Page, engine=None, lang: str = "ja",
             engine_name: str = "auto", relabel: bool = False,
             paint_weights: str = "") -> None:
    """Read every region on the page, and -- if asked -- say what each one IS.

    `relabel` is the reordered pipeline. See `readkinds`: the label costs
    nothing here because every region is read anyway, sound effects included,
    and the alternative is a second neural net whose whole job is that one
    question. Off by default and never on for a format it was not measured
    on; `Project` decides.

    `paint_weights` turns on the SECOND reader, for boxes in the sound-effect
    family. See `paintread`: manga-ocr is superb on typeset dialogue and a coin
    toss on hand-drawn paint, TRBA+2D is the other way round, and the two
    together halve the error over the 54 boxes both were measured on. Empty
    means the checkpoint is not on this machine, and then this behaves exactly
    as it did before the second reader existed.
    """
    engine = engine or get_engine(lang, engine_name)
    painter = None
    if paint_weights:
        from . import paintread
        if paintread.available(paint_weights):
            painter = paintread.get_reader(paint_weights)
    try:
        owner, idx_of = _pixel_owner(page)   # so overlaps aren't read twice
    except Exception:
        owner, idx_of = None, {}
    for r in page.regions:
        # Stop means stop. One check per REGION -- see `stopping` for why the
        # checkpoint is here and not inside the engine call.
        _stopping.check()
        # Somebody's own text box stands for no writing in the artwork. There
        # is nothing under it to read, and reading it anyway hands the
        # translator a crop of bare art and whatever the engine hallucinates
        # from it.
        if getattr(r, "own_text", False):
            continue
        # ...and a hand-corrected, LOCKED line is never overwritten by a
        # re-read. The same rule the editor's AI path has always kept; it
        # belongs here so that both readers keep it, rather than one of them.
        if getattr(r, "locked", False) and (r.src_text or "").strip():
            continue
        img = prepare_crop(page.image, r, owner, idx_of.get(r.id, -1))
        try:
            r.src_text = engine(img).strip()
        except Exception as e:
            r.src_text, r.ocr_ok = "", False
            r.flagged = f"ocr failed: {e}"
            continue
        # ...and a box in the sound-effect family is read a SECOND time, by the
        # reader that was trained on paint, and the two answers are settled by
        # `paintread.prefer`. Only this family: everywhere else manga-ocr is
        # already at 0.025 CER and TRBA cannot spell a kanji, so a second pass
        # there would cost 0.7s a box to make the page worse.
        #
        # A failure here is not a failed read. The first answer is already in
        # hand and it is the one the app had before this reader existed, so a
        # missing wheel or a broken checkpoint costs the page nothing.
        if painter is not None and r.src_text.strip() \
                and _kinds.family_of(getattr(r, "kind", "")) == "sfx":
            from . import paintread
            try:
                r.src_text = paintread.prefer(
                    r.src_text, paintread.read_one(img, painter))
            except Exception as e:      # noqa: BLE001 - never fail a page
                r.flagged = ((r.flagged or "")
                             + f" painted-text reader failed: {e}").strip()
        bad = looks_like_garbage(r.src_text, r)
        if bad:
            r.ocr_ok = False
            r.flagged = bad
        elif painter is None and r.src_text.strip() \
                and _kinds.family_of(getattr(r, "kind", "")) == "sfx":
            # A PAINTED SOUND READ BY manga-ocr ALONE IS WORTH LOOKING AT, and
            # this is the one place in the app where a wrong answer arrives
            # wearing a right one's face.
            #
            # Measured over every box the detector filed as a sound effect
            # across the 23 pages of chapter 3 - 54 of them, transcribed off
            # the page by eye:
            #
            #     typeset writing filed as sfx   CER 0.000   11/11 exact
            #     actually painted sounds        CER 0.401   24/43 exact
            #
            # The split is the whole story. manga-ocr was trained on typeset
            # dialogue and it is flawless on typeset dialogue even when the box
            # round it says otherwise. On paint it is a coin toss - and nine of
            # its misses are not misreadings at all, they are ordinary dialogue
            # words invented over a brush stroke: アア came back as そして,
            # バチャ as じゃあ and as ダメっ, ガチャッ as やっぱり, ドホ as いや.
            # That is the decoder's language model filling a silence, and it
            # produces a plausible Japanese line at full confidence.
            #
            # `looks_like_garbage` cannot see these: they are not garbage, they
            # are good Japanese in the wrong place. So the box says so itself.
            # A NOTE and not a verdict - the reading stays, `ocr_ok` stays true,
            # nothing is removed - because it is right more often than not.
            #
            # ONLY WHEN THE SECOND READER IS NOT HERE. With `paintread` running
            # the same boxes come back at 0.138 and the invented dialogue is
            # gone, so the note would be a warning about a problem that has
            # been fixed - and a warning on a box that is probably right is how
            # people learn to ignore warnings. The AI path carries no such note
            # either, for the same reason: it does not invent dialogue over
            # paint.
            r.flagged = ((r.flagged or "") + " read here: painted sounds are "
                         "this reader's weak spot — worth a look").strip()

    # ...AND NOW EVERY BOX HAS BEEN READ, SO EVERY BOX CAN BE NAMED.
    #
    # Done here rather than in the detector because this is the first moment
    # the evidence exists. Done AFTER the garbage check on purpose: a region
    # the reader returned nothing usable for is one `looks_like_a_sound`
    # should see as empty, which is the honest answer for a brush stroke.
    if relabel:
        from . import readkinds
        readkinds.relabel(page.regions)
