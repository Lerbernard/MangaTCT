"""Find text that is not inside a speech bubble.

Sound effects and unboxed dialogue sit directly on the artwork, so there is no
outline to look for. What they do have is a cluster of ink strokes with a
consistent stroke width and a lot of empty space around the cluster.

This is deliberately conservative: on a page of dense artwork almost anything
can look like a stroke, so it would rather miss a sound effect than hand back
a page covered in false boxes.

The second half of this file — `column_blocks` and `read_the_writing` — answers
the same question a different way, because the stroke-cluster method above
fragments a passage of vertical narration and misses most of it. See the
docstring on `column_blocks`.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..models import Page, TextRegion

INK = 110


class FreeTextConfig:
    min_area_frac = 0.0006      # of page area
    max_area_frac = 0.09
    gap = 13                    # px: strokes closer than this join one block
    min_components = 2          # a block needs at least this many strokes
    min_fill = 0.05             # ink / block area
    max_fill = 0.62
    max_stroke_frac = 0.05      # a stroke thicker than this is artwork
    border_margin = 4


def _stroke_width(comp: np.ndarray) -> float:
    """Twice the deepest point of a shape approximates its stroke width."""
    d = cv2.distanceTransform(comp.astype(np.uint8), cv2.DIST_L2, 3)
    return float(d.max() * 2.0)


def detect_free_text(page: Page, avoid: list[TextRegion] | None = None,
                     cfg: FreeTextConfig | None = None,
                     kind: str = "freefloat") -> list[TextRegion]:
    cfg = cfg or FreeTextConfig()
    img = page.image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    H, W = gray.shape
    page_area = H * W

    taken = np.zeros((H, W), np.uint8)
    for r in (avoid or []):
        m = r.place_mask()
        if m is not None:
            taken[m > 0] = 1

    ink = ((gray <= INK) & (taken == 0)).astype(np.uint8)

    # Group nearby strokes into blocks.
    k = np.ones((cfg.gap, cfg.gap), np.uint8)
    blocks = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, k)
    blocks = cv2.dilate(blocks, np.ones((3, 3), np.uint8))

    n, lab, stats, _ = cv2.connectedComponentsWithStats(blocks, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (cfg.min_area_frac * page_area <= w * h
                <= cfg.max_area_frac * page_area):
            continue
        if (x <= cfg.border_margin or y <= cfg.border_margin
                or x + w >= W - cfg.border_margin
                or y + h >= H - cfg.border_margin):
            continue

        block = (lab == i)
        block_ink = ink.astype(bool) & block
        fill = block_ink.sum() / max(1, w * h)
        if not (cfg.min_fill <= fill <= cfg.max_fill):
            continue

        ni, sub, sub_stats, _ = cv2.connectedComponentsWithStats(
            block_ink.astype(np.uint8), 8)
        strokes = [j for j in range(1, ni) if sub_stats[j, 4] >= 12]
        if len(strokes) < cfg.min_components:
            continue

        widest = max(_stroke_width(sub == j) for j in strokes)
        if widest > cfg.max_stroke_frac * max(w, h) * 2:
            continue                        # a solid shape, not typesetting

        mask = np.zeros((H, W), np.uint8)
        mask[block] = 255
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        hull = cv2.convexHull(max(cnts, key=cv2.contourArea))
        poly = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)

        glyph = np.zeros((H, W), np.uint8)
        glyph[block_ink] = 255
        out.append(TextRegion(
            id=len(out), bbox=(int(x), int(y), int(w), int(h)),
            text_mask=glyph, bubble_mask=mask,
            bubble_bbox=(int(x), int(y), int(w), int(h)),
            polygon=poly.reshape(-1, 2).tolist(),
            kind=kind, src_vertical=h > w * 1.3,
        ))
    return out


# ---------------------------------------------------------------------------
# Writing painted straight onto the art, read as columns
# ---------------------------------------------------------------------------

class ColumnConfig:
    ink_thresh = 110          # ink on art is printed solid; be strict
    min_glyph = 6             # a mark smaller than this is dust or a screen dot
    max_glyph = 60            # bigger than this is artwork, or a sound effect
    min_glyph_area = 20
    min_aspect = 0.12         # 「 and ー are extreme, and they are letters
    max_aspect = 8.0
    min_comp_fill = 0.10      # of its own bounding box, per mark
    col_gap = 0.9             # of a character, down a column
    col_drift = 0.55          # of a character, sideways within a column
    col_spread = 0.60         # of its own mean, per column: see _tidy
    col_straight = 0.22       # of the column's width: ditto
    body_size = 0.60          # a mark this big is a body character, not ruby
    blk_gap = 1.7             # of a character, between columns of one passage
    blk_overlap = 0.30        # how much two columns must run together
    size_ratio = 2.40         # ruby is half the body size and belongs with it
    min_glyphs = 6            # a passage worth typesetting
    min_block_fill = 0.30     # of its own box, per mark: see column_blocks
    min_stroke = 0.195        # stroke width over character size: see _measure
    max_stroke = 0.50         # ditto
    rule_span = 0.25          # of the page wide: a bar that long is a panel rule
    rule_cover = 0.90         # of the block's width, for a rule to cut it
    pad = 3
    panel_frac = 0.06         # a box this big is a suspect
    panel_cover = 0.50        # ...and if its writing fills less, it is a panel
    overlap_taken = 0.25      # leave alone anything a balloon finder got


def _marks(gray: np.ndarray, cfg: ColumnConfig):
    """Marks on the page that are the size and shape of a character."""
    ink = (gray <= cfg.ink_thresh).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in stats[i])
        if not (cfg.min_glyph <= w <= cfg.max_glyph):
            continue
        if not (cfg.min_glyph <= h <= cfg.max_glyph):
            continue
        if a < cfg.min_glyph_area:
            continue
        if not (cfg.min_aspect <= w / float(h) <= cfg.max_aspect):
            continue
        if a / float(w * h) < cfg.min_comp_fill:
            continue
        out.append((i, x, y, w, h, a))
    return lab, out


def _joinable(c, d, cfg: ColumnConfig) -> bool:
    """Are these two runs of marks the same column of writing?

    Sideways, their centres must agree to within about half a character; down
    the page, the white between them must be less than a character tall. Ruby —
    the tiny reading printed beside a kanji — is too far sideways to join, and
    comes back at the next step as a column of its own standing against its
    parent.
    """
    if abs(c["cx"] - d["cx"]) > cfg.col_drift * max(c["w"], d["w"]):
        return False
    reach = cfg.col_gap * max(c["h"], d["h"])
    return not (d["y0"] - c["y1"] > reach or c["y0"] - d["y1"] > reach)


def _stack(marks, by_id, cfg: ColumnConfig):
    """Japanese runs down the page, so characters stack into columns.

    Every mark starts as a column of one, and columns are merged until nothing
    more will join. The first version grew columns one mark at a time and never
    looked back, which quietly cut real columns in half: marks arrive in x
    order, so the third character of a column can be seen before the second,
    land too far below the head to join it, and start a rival column four
    pixels underneath. On lee's splash page that left the shout in eighteen
    fragments, every one too short and too ragged to be read as writing.
    Merging is order-free, so it cannot happen.
    """
    cols = [dict(cx=x + w / 2.0, w=w, h=h, x0=x, x1=x + w, y0=y, y1=y + h,
                 ids=[i])
            for i, x, y, w, h, a in sorted(marks, key=lambda t: (t[1], t[2]))]
    grew = True
    while grew:
        grew, out = False, []
        for c in cols:
            for d in out:
                if not _joinable(c, d, cfg):
                    continue
                d["x0"] = min(d["x0"], c["x0"])
                d["x1"] = max(d["x1"], c["x1"])
                d["y0"] = min(d["y0"], c["y0"])
                d["y1"] = max(d["y1"], c["y1"])
                d["cx"] = (d["x0"] + d["x1"]) / 2.0
                d["w"] = max(d["w"], c["w"])
                d["h"] = max(d["h"], c["h"])
                d["ids"] += c["ids"]
                grew = True
                break
            else:
                out.append(c)
        cols = out
    for c in cols:
        c["size"] = float(np.median(
            [max(by_id[i][3], by_id[i][4]) for i in c["ids"]]))
    return cols


def _tidy(col, by_id, cfg: ColumnConfig) -> bool:
    """Is this column a run of characters, or a trail of specks?

    Writing is set on a LINE. Whatever else varies down a column of Japanese —
    and a great deal does, because a full-size kanji, a small っ and a tiny ruby
    gloss all stand in the same column — the characters are hung on one axis,
    so their centres barely wander. Artwork does not do that: a spray of
    flowers, a hedge, a row of distant rooftops all drift as they go.

    Measured on lee's splash page, real columns wander by 0.05 to 0.19 of their
    own width and the artwork by 0.26 and up. Size spread is kept too, but held
    loose (0.60), because it is the mixing of kanji with ruby that pushes a real
    column's spread to 0.52 — reading that as artwork is exactly what threw
    away the whole of page 039 before.

    Pitch — the spacing between one character and the next — was measured here
    too and thrown out. It sounds like the strongest signal of all and it is
    not: real columns came in at 0.40, 0.51, 0.55, 0.70, 0.79, because a ruby
    mark sitting between two kanji halves one gap, and a character the ink
    threshold missed doubles another. It rejected nearly every true column on
    the page.
    """
    ids = col["ids"]
    if len(ids) < 2:
        return False
    s = np.array([max(by_id[i][3], by_id[i][4]) for i in ids], float)
    # Spread is asked of the FULL-SIZE characters only. A column of Japanese
    # is not one size, it is a body size with small companions hung beside it:
    # ruby at about a quarter of the area, a small っ, a run of dots. Measured
    # over everything, lee's "私…っ" came to 0.633 against a limit of 0.60 and
    # the column was thrown away as artwork — which is why the shout on his
    # page 38 was boxed one column wide, with 私…っ left outside it. Measured
    # over the body characters alone it is 0.11. Artwork gains nothing from
    # this: a spray of stipple has no body size to find, so dropping its small
    # marks leaves the rest just as ragged.
    body = s[s >= cfg.body_size * s.max()]
    if body.size < 2:
        body = s
    if float(body.std() / max(body.mean(), 1e-6)) > cfg.col_spread:
        return False
    cx = np.array([by_id[i][1] + by_id[i][3] / 2.0 for i in ids], float)
    wide = max(col["x1"] - col["x0"], 1)
    return float(cx.std() / wide) <= cfg.col_straight


def _passages(cols, cfg: ColumnConfig):
    """Columns standing shoulder to shoulder are one passage.

    Two columns belong together when the white between them is narrower than a
    character, they run down the page alongside each other, and their
    characters are the same size. That is what keeps the caption to the left of
    a drawing out of the box round the caption to its right — one sentence to a
    reader, two places to a typesetter, and a box spanning both would put English
    across the drawing between them.

    The reach is measured against the SMALLER of the two columns' own character
    size, and never against the group's. An earlier version took the largest
    character anywhere in the group, which meant every column joined widened
    the group's reach — so one 60-pixel shout at the left of a page dragged in
    everything across it, and whole panels came back as a single passage.
    """
    cols = sorted(cols, key=lambda c: -c["cx"])          # right to left
    used = [False] * len(cols)
    out = []
    for i in range(len(cols)):
        if used[i]:
            continue
        grp, used[i] = [i], True
        grew = True
        while grew:
            grew = False
            for k, d in enumerate(cols):
                if used[k]:
                    continue
                for j in grp:
                    c = cols[j]
                    lo = min(c["size"], d["size"])
                    if max(c["size"], d["size"]) > cfg.size_ratio * lo:
                        continue          # ruby aside, one passage is one size
                    gap = max(c["x0"] - d["x1"], d["x0"] - c["x1"], 0)
                    if gap > cfg.blk_gap * lo:
                        continue
                    run = min(c["y1"], d["y1"]) - max(c["y0"], d["y0"])
                    if run < cfg.blk_overlap * min(c["y1"] - c["y0"],
                                                   d["y1"] - d["y0"]):
                        continue
                    grp.append(k)
                    used[k] = True
                    grew = True
                    break
        mem = [cols[j] for j in grp]
        out.append(dict(
            x0=min(m["x0"] for m in mem), x1=max(m["x1"] for m in mem),
            y0=min(m["y0"] for m in mem), y1=max(m["y1"] for m in mem),
            cols=len(mem), ids=[i for m in mem for i in m["ids"]]))
    return out


def _measure(block, lab, by_id) -> None:
    """How thick the block is drawn, as a fraction of a character's size.

    Four times the area over the perimeter is the width of the band you would
    get if you unrolled the mark into a ribbon — a mark's stroke width, in
    other words, and the one number that says whether something is DRAWN like
    printing. Holes count towards the perimeter, which is right: a complex
    glyph full of counters is thinner than a blob of the same area.

    Divided by the character's size it is scale-free, so a 12-pixel caption and
    a 60-pixel shout give the same answer.
    """
    thin = []
    for i in block["ids"]:
        _, x, y, w, h, a = by_id[i]
        sub = np.pad((lab[y:y + h, x:x + w] == i).astype(np.uint8), 1)
        cnts, _ = cv2.findContours(sub, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        per = sum(cv2.arcLength(c, True) for c in cnts)
        thin.append(4.0 * a / max(per, 1.0))
    size = float(np.median(
        [max(by_id[i][3], by_id[i][4]) for i in block["ids"]]))
    block["stroke"] = float(np.median(thin)) / max(size, 1.0)


def _is_writing(block, by_id, cfg: ColumnConfig) -> bool:
    """What is left to ask of a block once every column in it is tidy.

    Nothing here is about size, which the old block-level test was: it compared
    a shout's 60-pixel characters against the ruby printed beside them and
    called the whole passage artwork.

    Enough of it to typeset, first, and ink that fills its little boxes the way
    printed characters do.

    Then how thickly it is DRAWN, which turned out to be the measure that
    matters. Print is cut to a stroke: run over lee's chapter, every real
    passage came in between 0.21 and 0.42 of a character's size, whether it was
    a 12-pixel caption or a 60-pixel shout. The false blocks sat outside on both
    sides — the flower embroidered on the dress on page 8 at 0.60, because it is
    a solid blob, and two long strands of the girl's hair on page 38 at 0.18 and
    0.17, because they are hairlines. Neither is written, and neither is drawn
    the way writing is.
    """
    if len(block["ids"]) < cfg.min_glyphs:
        return False
    w = np.array([by_id[i][3] for i in block["ids"]], float)
    h = np.array([by_id[i][4] for i in block["ids"]], float)
    a = np.array([by_id[i][5] for i in block["ids"]], float)
    if float((a / np.maximum(w * h, 1.0)).mean()) < cfg.min_block_fill:
        return False
    return cfg.min_stroke <= block.get("stroke", 0.0) <= cfg.max_stroke


def panel_rules(gray: np.ndarray, cfg: ColumnConfig) -> np.ndarray:
    """The straight bars of ink a page is ruled into panels with.

    A panel border is drawn from one side of the frame to the other, and
    nothing inside a passage of writing is anywhere near that long. Opening the
    ink with a brush a quarter of the page wide leaves the rules standing and
    takes every character, every hair and every flower away with it.
    """
    ink = (gray <= cfg.ink_thresh).astype(np.uint8)
    span = max(80, int(round(gray.shape[1] * cfg.rule_span)))
    return cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (span, 1)))


def _runs(ys: np.ndarray):
    """Consecutive rows, grouped: one rule is one run however thick it is."""
    out = []
    for y in ys:
        if out and y == out[-1][1] + 1:
            out[-1][1] = int(y)
        else:
            out.append([int(y), int(y)])
    return out


def _unruled(block, by_id, bar: np.ndarray, cfg: ColumnConfig) -> None:
    """Take back the marks that stand on the far side of a panel rule.

    No passage of writing crosses a panel border. `_straddles` says the same
    thing and says it too late and too weakly: it asks `detect_panels` for the
    frames, and on lee's page 8 the top panel bleeds off the paper so there is
    no white rectangle to find and no frame comes back. The border itself is
    still right there on the page — a black bar four hundred pixels long — and
    that is what this reads.

    The sprig of embroidery on the dress in that top panel is character-sized,
    stands in a tidy line, and sits directly above 落ちてたわよ in the panel
    beneath, so it stacks into the same column and the box came back reaching
    up out of the speech and into the dress. Cutting at the rule and keeping
    the side with more marks on it leaves the writing and drops the flowers.

    The block is modified in place, and only ever made smaller. If the cut
    would leave fewer than two marks the block is left exactly as it was:
    dropping a passage is worse than a box a little too tall.
    """
    ids = block["ids"]
    if len(ids) < 3:
        return
    x0, x1 = int(block["x0"]), int(block["x1"])
    seg = bar[:, x0:x1 + 1]
    if seg.shape[1] < 4:
        return
    across = seg.mean(axis=1) >= cfg.rule_cover
    ys = np.flatnonzero(across)
    ys = ys[(ys > block["y0"]) & (ys < block["y1"])]
    if not ys.size:
        return

    keep = set(ids)
    for lo, hi in _runs(ys):
        above = {i for i in ids if by_id[i][2] + by_id[i][4] <= lo}
        below = {i for i in ids if by_id[i][2] >= hi}
        keep &= above if len(above) >= len(below) else below
    if len(keep) < 2 or len(keep) == len(ids):
        return

    block["ids"] = [i for i in ids if i in keep]
    block["x0"] = min(by_id[i][1] for i in block["ids"])
    block["y0"] = min(by_id[i][2] for i in block["ids"])
    block["x1"] = max(by_id[i][1] + by_id[i][3] for i in block["ids"])
    block["y1"] = max(by_id[i][2] + by_id[i][4] for i in block["ids"])


def column_blocks(gray: np.ndarray, cfg: ColumnConfig | None = None):
    """Every passage of writing on the page, found from the ink alone.

    Every detector in `classical.py` is enclosure-first: it looks for a shape —
    a white blob, a dark outline — that HOLDS dark glyphs, and takes the inside
    of that shape as the region. That is the right way round for speech
    balloons and useless for the other half of a manga page, where a whole
    passage of narration is typeset directly over the drawing.

    lee sent back two pages showing both ways it fails. On one the text is
    simply MISSED: the shout down the middle of the splash got one box, 25
    pixels square, round a single kanji, and the passage beside it got nothing
    — there is no white shape round either to find. On the other it is found by
    ACCIDENT, when a pale panel background happens to enclose it, and then the
    box is the whole panel: one narration box 753x262 covering the toys, the
    flowers and both captions at once. That is lee's "box 5 spanning a whole
    panel".

    This asks the question from the other end: not "what shape is holding
    writing" but "which of these marks ARE writing". Marks of ink, kept if they
    are the size and shape of a character, stacked into columns, columns
    stacked into passages.

    Two measures do the separating, and both were arrived at by measuring the
    wrong thing first. Every number below was taken off lee's own pages, over
    nineteen blocks labelled by hand, before any of it was written down.

    STRAIGHTNESS, per column — the spread of the marks' centre-x over the
    column's own width. Writing is set on a LINE, and artwork is not:

    | column                        | straightness |
    |-------------------------------|--------------|
    | real columns of Japanese      | 0.05 - 0.19  |
    | hair, stipple, embroidery     | 0.26 and up  |

    The obvious measure here is PITCH — characters come at a regular spacing,
    artwork does not — and it was measured and thrown out. Real columns came in
    at 0.40, 0.47, 0.51, 0.55, 0.70, 0.79: a ruby mark between two kanji halves
    one gap and a missed character doubles the next, so a real column's pitch is
    all over the place. Rejecting on it threw away nearly every true column.

    THINNESS, per block — four times a mark's area over its perimeter, which is
    the width of the ribbon you would get by unrolling it, divided by the size
    of a character. Holes count towards the perimeter, and should: a kanji full
    of counters is drawn thinner than a blob of the same area.

    | block                        | thinness      |
    |------------------------------|---------------|
    | twelve real passages         | 0.212 - 0.423 |
    | two strands of hair          | 0.165, 0.183  |
    | embroidery on a dress        | 0.604         |

    That one holds across scale — 12px captions and 60px shouts sit in the same
    band — and it fails on both sides at once, which is why it works: artwork is
    either hairline-thin or a solid blob, and typesetting is neither. The measure
    that was tried before it, block-level size spread, separated cleanly on one
    page (0.09-0.20 text against 0.34-0.53 artwork) and collapsed on the next,
    because a shout mixed with its own furigana spreads 0.39-0.54. It is not
    scale-invariant and it is gone; what survives of it is the LOOSE per-column
    spread in `_tidy` and the local size test in `_passages`.

    Returns (labels, marks_by_id, blocks): the raw component labelling, so a
    caller can build an exact glyph mask, and the blocks that are writing.
    """
    cfg = cfg or ColumnConfig()
    lab, marks = _marks(gray, cfg)
    if not marks:
        return lab, {}, []
    by_id = {m[0]: m for m in marks}
    cols = [c for c in _stack(marks, by_id, cfg) if _tidy(c, by_id, cfg)]
    bar = panel_rules(gray, cfg)
    blocks = []
    for b in _passages(cols, cfg):
        _unruled(b, by_id, bar, cfg)
        _measure(b, lab, by_id)
        if _is_writing(b, by_id, cfg):
            blocks.append(b)
    return lab, by_id, blocks


def _block_region(block, lab, shape, cfg: ColumnConfig) -> TextRegion:
    """One passage, as a region the rest of the pipeline understands.

    It carries a rectangle for a polygon and NO balloon mask, so the fitter
    typesets it inside its box rather than inside a rectangle pretending to be
    a bubble outline — and so a save and a reload hands back the same thing.
    """
    H, W = shape[:2]
    x0 = max(0, block["x0"] - cfg.pad)
    y0 = max(0, block["y0"] - cfg.pad)
    x1 = min(W - 1, block["x1"] + cfg.pad)
    y1 = min(H - 1, block["y1"] + cfg.pad)
    want = np.zeros(int(lab.max()) + 2, bool)
    want[np.array(block["ids"], int)] = True
    mask = np.zeros((H, W), np.uint8)
    sub = lab[y0:y1 + 1, x0:x1 + 1]
    mask[y0:y1 + 1, x0:x1 + 1] = np.where(want[sub], 255, 0).astype(np.uint8)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    return TextRegion(
        id=-1, bbox=(x0, y0, w, h), text_mask=mask,
        bubble_mask=None, bubble_bbox=(x0, y0, w, h),
        polygon=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        kind="freefloat", src_vertical=h > w * 1.15)


def _overlap(a, b) -> float:
    """How much of box `a` box `b` covers."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return ix * iy / float(max(1, aw * ah))


def _straddles(box, frames) -> bool:
    """Does this box have a real foot in two different panels?

    Panel finding is approximate by design, so a box is only called a
    straddler when two panels each hold a fifth of it and neither holds it
    whole — enough to catch a column that has stacked down through a gutter,
    and not enough for a rounded panel corner to trigger it.
    """
    if not frames:
        return False
    share = [_overlap(box, f) for f in frames]
    if max(share) >= 0.95:
        return False
    return sum(1 for s in share if s >= 0.20) >= 2


def not_already_read(loose: list[TextRegion], taken: list[TextRegion],
                     cover: float = 0.35) -> list[TextRegion]:
    """Of the stroke pass's blocks, the ones the column reader did not get.

    The two passes have to be shown the SAME ink, or the stroke pass changes
    its mind about pages it was never asked about. It groups ink by closing it
    with a 13-pixel brush, so on lee's page 10 the two toy rabbits closed
    together with the caption beside them into one block, which was then thrown
    out for being the wrong shape. Blank out the caption first — which is what
    handing it the reader's boxes to avoid does — and the rabbits stand alone,
    pass every test, and come back as a box round a drawing of two rabbits.

    So the stroke pass is run on the untouched page, exactly as it always was,
    and what it hands back is compared with the reader's boxes afterwards. A
    block a third covered by writing that has already been read is that
    writing, seen a second time.
    """
    out = []
    for r in loose:
        if not any(_overlap(r.bbox, t.bbox) >= cover for t in taken):
            out.append(r)
    return out


def absorb_fragments(regions: list[TextRegion],
                     cover: float = 0.85, times: float = 3.0
                     ) -> list[TextRegion]:
    """A body of writing is one box, so the crumbs beside it are dropped.

    lee, on two crops of his own pages: "make the box be one text the second
    and third picture shoud be one box for example". Reading the writing first
    puts one box round the whole passage, but the enclosure-first detectors have
    already been over the page and they leave crumbs inside it — a box round the
    single kanji 国, because the white counter inside the character looked like a
    tiny balloon, and a box round the ruby printed beside it.

    A region is a crumb when a passage of writing swallows it whole and is
    several times its size. Both conditions matter: overlap alone would eat a
    small balloon that happened to fall inside a passage's rectangle, and size
    alone would eat a caption standing next to a shout.

    Only writing read column by column may swallow anything. Those regions carry
    no balloon mask, so their box is a plain rectangle round a body of text, and
    they are the only regions on the page that KNOW they are one passage.
    """
    keep = list(regions)
    eaters = [r for r in keep
              if r.bubble_mask is None and r.kind in ("freefloat", "narration")]
    out = []
    for r in keep:
        area = max(1, r.bbox[2] * r.bbox[3])
        eaten = False
        for big in eaters:
            if big is r:
                continue
            if big.bbox[2] * big.bbox[3] < times * area:
                continue
            if _overlap(r.bbox, big.bbox) >= cover:
                eaten = True
                break
        if not eaten:
            out.append(r)
    return out


def read_the_writing(page: Page, found: list[TextRegion],
                     cfg: ColumnConfig | None = None
                     ) -> list[TextRegion]:
    """Fix the boxes that are panels, and add the writing nobody found.

    Two faults, one cause, so one pass:

    * a region whose box is a large part of the page and whose writing fills
      only a corner of it is not a balloon, it is a **panel** that happened to
      be pale enough to enclose some captions. It is replaced by the passages
      inside it, so lee gets a box per caption instead of one round the whole
      panel;
    * and any passage nobody has a box for is added.

    `found` is modified in place — panels are removed from it — and the new
    regions come back to be appended. Ids are not touched; the caller hands
    them out.
    """
    cfg = cfg or ColumnConfig()
    img = page.image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    H, W = gray.shape[:2]
    lab, _, blocks = column_blocks(gray, cfg)
    if not blocks:
        return []
    boxes = [(b["x0"], b["y0"], b["x1"] - b["x0"] + 1, b["y1"] - b["y0"] + 1)
             for b in blocks]

    # 1. Which of the boxes already found are panels wearing a balloon's coat?
    panels = []
    for r in found:
        bb = r.bubble_bbox or r.bbox
        if bb[2] * bb[3] < cfg.panel_frac * H * W:
            continue
        mine = [i for i, bx in enumerate(boxes) if _overlap(bx, bb) > 0.85]
        if not mine:
            continue
        cover = sum(boxes[i][2] * boxes[i][3] for i in mine) \
            / float(max(1, bb[2] * bb[3]))
        if cover < cfg.panel_cover:
            panels.append(r)
    for r in panels:
        found.remove(r)

    # 2. Every passage nobody has a box for now becomes one — unless it runs
    #    across a panel border, which no passage of writing ever does. On lee's
    #    page 8 a sprig of embroidery on a dress in the top panel stacked
    #    straight down into the speech below it and came back as one tall box
    #    crossing the gutter between them.
    from .classical import detect_panels          # circular at module level
    frames = detect_panels(page)
    out: list[TextRegion] = []
    for b, bx in sorted(zip(blocks, boxes), key=lambda t: (t[1][1], -t[1][0])):
        if _straddles(bx, frames):
            continue
        if any(_overlap(bx, r.bubble_bbox or r.bbox) > cfg.overlap_taken
               for r in found):
            continue
        if any(_overlap(bx, r.bbox) > cfg.overlap_taken for r in out):
            continue
        out.append(_block_region(b, lab, gray.shape, cfg))
    return out
