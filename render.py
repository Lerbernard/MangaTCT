"""Render the translated page, and the side-by-side reader (stage 1)."""
from __future__ import annotations

import html

import cv2
import numpy as np
from PIL import (Image, ImageChops, ImageDraw, ImageFilter, ImageFont,
                   ImageOps)

from . import kinds as _kinds
from .models import Page
from .typeset import (OUTLINE_IN_BUBBLE, OUTLINE_ON_ART, TypesetConfig, _font,
                      on_art,
                      default_font_path, em_dash_glyph)


def stroke_for(region, automatic: int) -> int:
    """An outline width set by hand beats the automatic choice.

    Both the colour pass and the drawing pass work this out independently, so
    the rule lives in one place — applying it in only one of them meant the
    control moved the preview and left the exported page alone.
    """
    ov = region.layout_override or {}
    if ov.get("stroke") not in (None, ""):
        return max(0, min(30, int(ov["stroke"])))
    return int(automatic)


def hex_rgb(s):
    """'#rrggbb' -> (r, g, b, 255), or None if it is not a colour."""
    if not isinstance(s, str):
        return None
    s = s.strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        n = int(s, 16)
    except ValueError:
        return None
    return ((n >> 16) & 255, (n >> 8) & 255, n & 255, 255)


def colours_for(region, fg, edge):
    """Text and outline colours set by hand beat the automatic choice."""
    ov = region.layout_override or {}
    return (hex_rgb(ov.get("fg")) or fg,
            hex_rgb(ov.get("edge")) or edge)


def _draw_em_dash(d, cx, y, adv, bar, fill=None, stroke_width=0,
                  stroke_fill=None, **_):
    """A borrowed em-dash, for a font that lacks the glyph.

    `bar` carries an alpha mask of the dash (see typeset.em_dash_glyph); it is
    stamped through ImageDraw.bitmap so it takes the text colour. The outline
    is the same mask grown by the stroke width, stamped underneath."""
    _, top, mask = bar
    x = int(round(cx + (adv - mask.width) / 2.0))
    yy = int(round(y + top))
    if stroke_width and stroke_fill is not None:
        sw = int(stroke_width)
        grown = ImageOps.expand(mask, border=sw, fill=0)
        grown = grown.filter(ImageFilter.MaxFilter(2 * sw + 1))
        d.bitmap((x - sw, yy - sw), grown, fill=stroke_fill)
    d.bitmap((x, yy), mask, fill=fill)


def arc_places(line, f, lspace, curve, x, y):
    """Where each letter of a curved line sits, and how far it is turned.

    A curved line is the same letters with the same advances, walked around a
    circle instead of along a straight baseline. `curve` is the whole angle the
    line subtends, in degrees, so it means the same thing whatever the words are
    or how big they are: 60 is the same bend on "OH" as on "OH NO, LOOK OUT".
    Positive arches up like a rainbow — the middle is highest — and negative
    sags. The radius follows from the arc length: R = length / angle.

    Returns [(cx, cy, degrees, char, advance)], one per character, with the
    centre of each letter's advance on the arc and the tangent there. The same
    arithmetic is in `typesetting.js`, and a test compares the two.
    """
    import math
    widths = [f.getlength(ch) for ch in line]
    total = sum(widths) + lspace * max(0, len(line) - 1)
    ang = math.radians(float(curve))
    if total <= 0 or abs(ang) < 1e-4:
        return None
    R = total / ang                     # signed: the sign is the direction
    # The bend has to keep the line where the fitter put it. Hung from the
    # middle, an arch sinks by its whole sagitta — at 140 degrees that is a
    # third of the line's length, and the words walk off the bottom of the box.
    # Half the sagitta comes back off, so the ink stays balanced about the
    # straight line's own row: the middle rides as far up as the ends ride down.
    sag = R * (1.0 - math.cos(ang / 2.0))
    out = []
    s = -total / 2.0
    for ch, wd in zip(line, widths):
        th = (s + wd / 2.0) / R
        out.append((x + R * math.sin(th),
                    y + R * (1.0 - math.cos(th)) - sag / 2.0,
                    math.degrees(th), ch, wd))
        s += wd + lspace
    return out


def _letter_mask(f, ch, adv, pad=0, bar=None):
    """One character as an alpha mask, and where it goes relative to the arc.

    The offset is measured from the middle of the character's own advance, on
    the line's middle — the same anchor the straight path draws from. Measuring
    from the mask's own centre instead is what lifted every comma and descender
    onto the baseline, because a comma's box is nowhere near its letter's.
    """
    if bar is not None and ch == "—":
        _, top, m = bar
        if pad:
            m = ImageOps.expand(m, border=pad, fill=0)
        return m, (adv - m.width) / 2.0 - adv / 2.0 - pad, top - pad
    x0, y0, x1, y1 = f.getbbox(ch, anchor="lm")
    w, h = max(1, int(x1 - x0) + 1), max(1, int(y1 - y0) + 1)
    m = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
    # Drawn so the ink's own corner lands at (pad, pad): with anchor "lm" the
    # ink runs from the anchor + (x0, y0), and y0 is NEGATIVE for anything with
    # an ascender — anchoring at (pad, pad) itself drew every capital off the
    # top of its own mask and stamped the leftovers.
    ImageDraw.Draw(m).text((pad - x0, pad - y0), ch, font=f, fill=255,
                           anchor="lm")
    # so the mask's corner sits at (x0 - pad, y0 - pad) from the anchor, and
    # the anchor is half an advance left of the point on the arc
    return m, x0 - pad - adv / 2.0, y0 - pad


def _draw_curved(d, places, f, bar=None, fill=None, stroke_width=0,
                 stroke_fill=None, **_):
    """A curved line, one turned letter at a time.

    `ImageDraw.text` cannot rotate, so each letter is rendered as its own mask,
    turned, and stamped through `ImageDraw.bitmap` — which takes a colour, so
    the same code paints the letters on a page and the letters into a mask
    (the gradient and inner-glow passes both need the second).

    The outline is stamped for the WHOLE line before any fill is, or a letter's
    outline would sit on top of the one before it and eat into its face.
    """
    import math
    sw = int(stroke_width or 0)
    for do_stroke in ((True, False) if (sw and stroke_fill is not None)
                      else (False,)):
        for cx, cy, deg, ch, adv in places:
            if not ch.strip():
                continue
            pad = sw if do_stroke else 0
            m, ox, oy = _letter_mask(f, ch, adv, pad, bar)
            if do_stroke:
                m = m.filter(ImageFilter.MaxFilter(2 * sw + 1))
            gw, gh = m.size
            # the letter turns about the arc point, so its own centre swings
            # round with it — rotate the offset, then place the turned mask
            mid = (ox + gw / 2.0, oy + gh / 2.0)
            m = m.rotate(-deg, resample=Image.BICUBIC, expand=True)
            a = math.radians(deg)
            rx = mid[0] * math.cos(a) - mid[1] * math.sin(a)
            ry = mid[0] * math.sin(a) + mid[1] * math.cos(a)
            d.bitmap((int(round(cx + rx - m.width / 2.0)),
                      int(round(cy + ry - m.height / 2.0))), m,
                     fill=(stroke_fill if do_stroke else fill))


def draw_line(d, x, y, line, f, lspace=0.0, curve=0.0, **kw):
    """One line of text, centred at (x, y), with optional letter spacing.

    An em-dash is drawn by hand when the font has no glyph for it, so comic
    faces that ship only a hyphen still show a real long dash."""
    bar = None
    if "—" in line:
        bar = em_dash_glyph(getattr(f, "path", "") or "",
                            int(getattr(f, "size", 0)))
    if curve:
        places = arc_places(line, f, lspace, curve, x, y)
        if places:
            # A hand-drawn em-dash is a stamped bitmap rather than a glyph, so
            # a curved line falls back to the font's own dash for it. Nobody
            # curves a line of dashes; losing the curve on one is worse.
            _draw_curved(d, places, f, bar=bar, **kw)
            return
    if not lspace and not bar:
        d.text((x, y), line, font=f, anchor="mm", **kw)
        return
    widths = [(bar[0] if (bar and ch == "—") else f.getlength(ch)) for ch in line]
    total = sum(widths) + lspace * max(0, len(line) - 1)
    cx = x - total / 2.0
    for ch, wd in zip(line, widths):
        if bar and ch == "—":
            _draw_em_dash(d, cx, y, wd, bar, **kw)
        else:
            d.text((cx, y), ch, font=f, anchor="lm", **kw)
        cx += wd + lspace


def _gradient_image(size, bbox, c0, c1, angle_deg):
    """A full-size RGBA image blending c0 -> c1 across bbox.

    angle 0 runs top to bottom, 90 left to right, and so on clockwise —
    the same convention the editor's preview uses.
    """
    import math
    w, h = size
    x0, y0, x1, y1 = bbox
    a = math.radians(angle_deg % 360.0)
    dx, dy = math.sin(a), math.cos(a)
    xs = np.arange(w, dtype=np.float32)[None, :]
    ys = np.arange(h, dtype=np.float32)[:, None]
    proj = xs * dx + ys * dy
    corners = [x0 * dx + y0 * dy, x1 * dx + y0 * dy,
               x0 * dx + y1 * dy, x1 * dx + y1 * dy]
    pmin, pmax = min(corners), max(corners)
    t = np.clip((proj - pmin) / max(1e-6, pmax - pmin), 0.0, 1.0)
    out = np.empty((h, w, 4), np.uint8)
    for i in range(4):
        out[..., i] = (c0[i] + (c1[i] - c0[i]) * t).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def assign_colours(page: Page, cfg: TypesetConfig | None = None) -> None:
    """Work out and record each region's typesetting colours.

    Done at typeset time rather than render time so the browser can draw a
    live preview that matches the exported page.
    """
    cfg = cfg or TypesetConfig()
    # Colours are read off the artwork, so a page with no artwork to read —
    # a stand-in built to exercise the fitter alone — simply keeps whatever
    # colours it already had rather than failing the lay-out.
    orig = getattr(page, "image", None)
    plate = getattr(page, "clean_plate", None)
    base = plate if plate is not None else orig
    if base is None:
        return
    for r in page.regions:
        lay = r.layout
        if not lay or not lay.lines:
            continue
        fg, edge, stroke = _ink_colours(base, r, lay, on_art(r), orig=orig)
        fg, edge = colours_for(r, fg, edge)
        stroke = stroke_for(r, stroke)
        lay.fg = "#%02x%02x%02x" % fg[:3]
        lay.edge = "#%02x%02x%02x" % edge[:3]
        lay.stroke = int(stroke)


def render_page(page: Page, cfg: TypesetConfig | None = None,
                halo: bool = True, debug: bool = False,
                clip: bool = True, only=None,
                bare: bool = False) -> np.ndarray:
    """Draw the English onto the cleaned page.

    Each region's text is drawn on its own transparent layer and composited
    through that region's mask, so typesetting physically cannot land outside
    the box it belongs to. The fitter tries hard to avoid overflow in the
    first place; this is the guarantee behind it.

    `only` restricts it to a set of region ids and `bare` starts from clear
    paper instead of the plate and hands back RGBA. Together they are one
    block's typesetting as a picture — which is what turning a text layer into
    an image layer needs. lee: *"allow me to turn text layer into image
    layers"*. The colours are chosen against the real page either way, so the
    picture is the typesetting as it looks where it stands.
    """
    cfg = cfg or TypesetConfig()
    if not cfg.font_path:
        cfg.font_path = default_font_path()

    base = page.clean_plate if page.clean_plate is not None else page.image
    if bare:
        pil = Image.new("RGBA", (base.shape[1], base.shape[0]), (0, 0, 0, 0))
    else:
        pil = Image.fromarray(cv2.cvtColor(base, cv2.COLOR_BGR2RGB))

    for r in page.ordered():
        if only is not None and r.id not in only:
            continue
        lay = r.layout
        if not lay or not lay.lines:
            continue
        f = _font(lay.font_path or cfg.font_path, lay.font_size)
        needs_halo = halo and on_art(r)

        fg, edge, stroke = _ink_colours(base, r, lay, needs_halo,
                                        orig=page.image)
        fg, edge = colours_for(r, fg, edge)
        stroke = stroke_for(r, stroke)

        layer = Image.new("RGBA", pil.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        ov = r.layout_override or {}
        lsp = float(ov.get("lspace") or 0.0)
        # How far the line bends: degrees of arc across the whole line.
        crv = float(ov.get("curve") or 0.0)
        shcol = hex_rgb(ov.get("shadow"))
        if shcol:
            dist = float(ov.get("sh_dist") if ov.get("sh_dist")
                         not in (None, "") else 2)
            blur = float(ov.get("sh_blur") if ov.get("sh_blur")
                         not in (None, "") else 3)
            offx, offy = dist * 0.707, dist * 0.707
            sh = Image.new("RGBA", pil.size, (0, 0, 0, 0))
            ds = ImageDraw.Draw(sh)
            for (x, y), line in zip(lay.line_origins, lay.lines):
                draw_line(ds, x + offx, y + offy, line, f, lsp, crv,
                          fill=shcol, stroke_width=stroke, stroke_fill=shcol)
            if blur > 0:
                sh = sh.filter(ImageFilter.GaussianBlur(blur))
            layer = Image.alpha_composite(layer, sh)
            d = ImageDraw.Draw(layer)

        # An OUTER GLOW: the same letters, spread outwards and blurred, sitting
        # under everything. A shadow with no offset is not the same thing — a
        # glow has to be grown before it is blurred or it stays inside the
        # letters and never shows past the outline. So the silhouette is drawn
        # with a fat stroke (`spread`) and blurred by about half of it, and the
        # result is stacked so the halo is dense enough to read on artwork
        # rather than a grey breath. Photoshop's Size and Spread, in one knob.
        glcol = hex_rgb(ov.get("glow"))
        if glcol:
            size = float(ov.get("glow_size") if ov.get("glow_size")
                         not in (None, "") else 6)
            if size > 0:
                spread = max(1, int(round(size)))
                gl = Image.new("RGBA", pil.size, (0, 0, 0, 0))
                dg = ImageDraw.Draw(gl)
                for (x, y), line in zip(lay.line_origins, lay.lines):
                    draw_line(dg, x, y, line, f, lsp, crv, fill=glcol,
                              stroke_width=stroke + spread, stroke_fill=glcol)
                gl = gl.filter(ImageFilter.GaussianBlur(size * 0.55))
                for _ in range(2):
                    layer = Image.alpha_composite(layer, gl)
                d = ImageDraw.Draw(layer)

        for (x, y), line in zip(lay.line_origins, lay.lines):
            draw_line(d, x, y, line, f, lsp, crv, fill=fg,
                      stroke_width=stroke, stroke_fill=edge)

        # ...and a second colour on the OUTLINE turns that into a gradient too.
        # lee: *"can you make it so that i can add gradient to the ouline of
        # the text"*.
        #
        # The mask is the ring and only the ring: drawn with the stroke lit and
        # the fill dark, so the glyph the stroke was drawn around is punched
        # back out of it. Painting through the whole stroked shape instead
        # would lay the outline's gradient across the letters as well, and then
        # the fill — its own colour or its own gradient — would be repainting
        # over the top of it, which is two answers to one question.
        edge2 = hex_rgb(ov.get("edge2"))
        if edge2 and stroke > 0:
            ring = Image.new("L", pil.size, 0)
            dr = ImageDraw.Draw(ring)
            for (x, y), line in zip(lay.line_origins, lay.lines):
                draw_line(dr, x, y, line, f, lsp, crv, fill=0,
                          stroke_width=stroke, stroke_fill=255)
            rbox = ring.getbbox()
            if rbox:
                grad = _gradient_image(pil.size, rbox,
                                       hex_rgb(ov.get("edge1")) or edge, edge2,
                                       float(ov.get("edge_angle") or 0))
                layer.paste(grad, (0, 0), ring)

        # A second colour turns the fill into a gradient. The letters are
        # repainted through their own mask, so the outline keeps its colour.
        fg2 = hex_rgb(ov.get("fg2"))
        if fg2:
            gm = Image.new("L", pil.size, 0)
            dm = ImageDraw.Draw(gm)
            for (x, y), line in zip(lay.line_origins, lay.lines):
                draw_line(dm, x, y, line, f, lsp, crv, fill=255)
            bbox = gm.getbbox()
            if bbox:
                grad = _gradient_image(pil.size, bbox,
                                       hex_rgb(ov.get("fg1")) or fg, fg2,
                                       float(ov.get("grad_angle") or 0))
                layer.paste(grad, (0, 0), gm)

        # An INNER GLOW: light coming from the letter's own edge, inwards.
        # There is no offset and no spread to play with — the whole effect is
        # "how far in from the edge am I", and the cheapest honest measure of
        # that is the glyph mask's own blurred inverse: just inside the edge it
        # is bright, and it falls away towards the middle of the stroke. That
        # ramp becomes the alpha, and it is clipped back to the letters so not
        # a pixel of it lands on the artwork.
        igcol = hex_rgb(ov.get("iglow"))
        if igcol:
            isize = float(ov.get("iglow_size") if ov.get("iglow_size")
                          not in (None, "") else 5)
            if isize > 0:
                im = Image.new("L", pil.size, 0)
                di = ImageDraw.Draw(im)
                for (x, y), line in zip(lay.line_origins, lay.lines):
                    draw_line(di, x, y, line, f, lsp, crv, fill=255)
                inv = ImageChops.invert(im).filter(
                    ImageFilter.GaussianBlur(isize * 0.6))
                a = np.array(inv, np.float32) * (np.array(im, np.float32) / 255.0)
                # a blurred edge tops out near half, so it is lifted to reach
                # full strength right at the rim
                a = np.clip(a * 2.1, 0, 255).astype(np.uint8)
                tint = Image.new("RGBA", pil.size, igcol)
                layer = Image.alpha_composite(
                    layer, Image.merge("RGBA", (*tint.split()[:3],
                                                Image.fromarray(a, "L"))))

        # TRANSPARENCY. It belongs to the whole block — letters, outline,
        # shadow, both glows — so it goes on once, here, after everything that
        # draws and before the balloon clips it. Fading the composited PAGE
        # instead would fade the artwork with it.
        op = ov.get("opacity")
        if op not in (None, ""):
            k = max(0.0, min(1.0, float(op) / 100.0))
            if k < 1.0:
                layer.putalpha(layer.split()[3].point(
                    lambda v, k=k: int(round(v * k))))

        frame = getattr(lay, "frame", None)
        if getattr(lay, "rotate", 0):
            if frame:
                cx, cy = frame[0] + frame[2] / 2.0, frame[1] + frame[3] / 2.0
            else:
                cx = sum(x for x, _ in lay.line_origins) / len(lay.line_origins)
                cy = sum(y for _, y in lay.line_origins) / len(lay.line_origins)
            layer = layer.rotate(lay.rotate, resample=Image.BICUBIC,
                                 center=(cx, cy))

        # Text with a frame of its own is not clipped to the bubble. Clipping
        # it there is what made rotation look like it did nothing: the layer
        # turned, then everything outside the box was cut straight back off.
        # Every block carries a frame now, so having one says nothing about
        # whether a person put it there: ask the two questions that actually
        # mean "leave this alone" instead.
        free = _kinds.family_of(r.kind) == "sfx" or bool(
            (r.layout_override or {}).get("locked"))
        # ...and a block set at the minimum size BECAUSE it would not fit its
        # box. Cutting it back to the box here is the spill being undone at the
        # last possible moment, with the words simply missing their first and
        # last letters on the exported page. lee: *"outside text and sfx shoud
        # be able to got outside teh box if the text size is bellow the
        # miimum"*.
        free = free or bool(getattr(lay, "spills", False))
        area = None if free else (r.place_mask() if clip else None)
        if area is not None:
            keep = Image.fromarray((area > 0).astype(np.uint8) * 255, "L")
            alpha = Image.fromarray(
                np.minimum(np.array(layer.split()[3]), np.array(keep)), "L")
            layer.putalpha(alpha)
        pil = Image.alpha_composite(pil.convert("RGBA"), layer)

    if bare:
        # RGBA, in OpenCV's channel order, so it can be PNG-encoded and dropped
        # straight into the paint stack.
        return cv2.cvtColor(np.array(pil.convert("RGBA")), cv2.COLOR_RGBA2BGRA)

    out = cv2.cvtColor(np.array(pil.convert("RGB")), cv2.COLOR_RGB2BGR)

    if debug:
        for r in page.ordered():
            if r.bubble_bbox:
                x, y, w, h = r.bubble_bbox
                col = (0, 0, 255) if r.flagged else (0, 170, 0)
                cv2.rectangle(out, (x, y), (x + w, y + h), col, 1)
                cv2.putText(out, str(r.order), (x + 3, y + 16),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
    return out


DARK_BG = 118          # mean brightness below this counts as a dark background


def original_tone(orig, region) -> int:
    """Which way round the Japanese in this region was printed.

    The English is meant to take the colour of the text it replaces, and the
    only place that colour still exists is the page as it arrived: by the time
    anything is typeset the balloon has been cleaned flat and the evidence is
    gone. So this reads the ORIGINAL scan inside the box where the Japanese
    was, splits it into two populations, and reports which of the two was the
    writing.

    The region's own `text_mask` cannot answer this. It is built as "dark
    pixels inside the bubble", so on a black balloon with white kana it selects
    the balloon and not a single stroke of the writing. Otsu makes no such
    assumption — it just finds the two populations — and the ink is then named
    by the one thing that is true of ink and false of everything else on the
    page: THERE IS MORE OF IT WHERE THE TEXT IS THAN THERE IS AROUND IT. So the
    same split is applied to the rest of the balloon, outside the text box, and
    whichever class the text box has a bigger share of is the writing.

    That test survives the case a brightness rule cannot: a balloon filled with
    vertical hatching, whose average is nowhere near black, carrying white
    typesetting. Averages call that a light background and typeset it black-on-
    dark; comparing inside against outside sees the hatch give way to white
    exactly where the words are, and calls it white.

    With no surroundings to compare against — a sound effect sitting out on the
    artwork, or a box that already covers the whole balloon — it falls back to
    the next most reliable thing: writing is a minority of its own box.

    Returns +1 for light typesetting on dark, -1 for dark typesetting on light, and
    0 when the evidence is too thin to say, which leaves the caller to fall
    back to the brightness of the background.
    """
    if orig is None or getattr(orig, "size", 0) == 0:
        return 0
    bb = getattr(region, "bbox", None)
    if not bb or len(bb) != 4:
        return 0

    H, W = orig.shape[:2]
    x, y, w, h = (int(v) for v in bb)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + max(1, w)), min(H, y + max(1, h))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return 0

    g = cv2.cvtColor(orig, cv2.COLOR_BGR2GRAY) if orig.ndim == 3 else orig
    box = np.zeros((H, W), bool)
    box[y0:y1, x0:x1] = True

    place = region.place_mask()
    inside = box if place is None else (box & (place > 0))
    if int(inside.sum()) < 60:
        inside = box                      # the box missed the mask; trust it
        if int(inside.sum()) < 60:
            return 0

    vals = g[inside]
    if float(vals.max()) - float(vals.min()) < 40:
        return 0                          # flat paper: nothing was written here

    t, _ = cv2.threshold(vals.reshape(-1, 1).astype(np.uint8), 0, 255,
                         cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark_in = float((vals <= t).mean())
    if not 0.02 <= dark_in <= 0.98:
        return 0                          # one population only; no writing

    # What surrounds the writing. The balloon is the ideal answer, but masks are
    # not saved with a chapter, so after a reload there is no balloon to ask
    # about — and that is precisely when this used to fall through to the coin
    # flip below and typeset a dark hatched balloon black. A ring drawn just
    # outside the text box is background wherever the text box is a text box,
    # so the inside-versus-around test can run in both cases.
    out = None
    if place is not None:
        out = (place > 0) & ~box
        if int(out.sum()) < 60:
            out = None
    if out is None:
        pad = max(6, int(0.30 * min(x1 - x0, y1 - y0)))
        ring = np.zeros((H, W), bool)
        ring[max(0, y0 - pad):min(H, y1 + pad),
             max(0, x0 - pad):min(W, x1 + pad)] = True
        out = ring & ~box
        if place is not None:
            out &= (place > 0)            # never wander off the balloon
        if int(out.sum()) < 60:
            out = None

    ink_is_light = None
    if out is not None:
        dark_out = float((g[out] <= t).mean())
        if abs(dark_in - dark_out) >= 0.04:
            # More of one class here than around here: that is the writing.
            ink_is_light = dark_in < dark_out
    if ink_is_light is None:
        ink_is_light = dark_in > 0.5      # the writing is the smaller share

    return 1 if ink_is_light else -1


def _bg_under(base: np.ndarray, region, lay) -> tuple[float, float]:
    """How dark the page is exactly where the words are going to land.

    Sampled along the lines themselves rather than over the whole bubble: a
    bubble can be light overall and still have a line of text crossing a dark
    patch. Returns the mean brightness and the share of it that is dark —
    an average is the wrong question for hatching, where fine white lines on
    black average to grey and land either side of a threshold by luck, while
    what actually decides whether black typesetting can be read there is how
    much of the paper under the words is dark.
    """
    mask = region.place_mask()
    band = np.zeros(base.shape[:2], np.uint8)
    h = max(6, int(lay.font_size * 0.8))
    for (x, y) in lay.line_origins:
        y0, y1 = max(0, int(y) - h), min(base.shape[0], int(y) + h)
        x0, x1 = max(0, int(x) - h * 6), min(base.shape[1], int(x) + h * 6)
        band[y0:y1, x0:x1] = 1
    # With no mask at all — nothing detected, nothing reloaded — the strip the
    # words will occupy is still a fair sample, and a fair sample beats
    # assuming white paper.
    sel = (band > 0) if mask is None else ((mask > 0) & (band > 0))
    if sel.sum() < 20 and mask is not None:
        sel = mask > 0
    if not sel.sum():
        return 255.0, 0.0
    g = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY) if base.ndim == 3 else base
    return float(g[sel].mean()), float((g[sel] < 128).mean())


def _ink_colours(base: np.ndarray, region, lay, needs_halo: bool, orig=None):
    """Pick typesetting colours to match the text this region replaces.

    The original page decides when it can be read: writing that was light on
    dark comes back white with a black edge, writing that was dark on light
    comes back black with a white edge. When the original has nothing clear to
    say the background decides instead — dark artwork gets white typesetting,
    everything else black. Either way the edge is the opposite colour, which is
    invisible inside a plain white bubble and does the work over tone and art.
    """
    tone = original_tone(orig, region)
    mean, dark_frac = _bg_under(base, region, lay)

    # Black typesetting on a dark background cannot be read, whatever the
    # original said. `original_tone` reads the page AS IT ARRIVED, but the
    # words are drawn on the page as it is NOW: the cleaner can leave dark art
    # where a balloon used to be, a frame can be dragged out onto a black
    # panel, and the answer the original gave stops being true. So a decidedly
    # dark background always gets white typesetting with a black edge — the one
    # thing lee has asked for every time this has come up.
    dark_bg = mean < DARK_BG or dark_frac >= 0.55

    if tone > 0 or dark_bg:
        fg, edge = (255, 255, 255, 255), (0, 0, 0, 255)
        width = max(OUTLINE_ON_ART, lay.font_size // 7)
    else:
        fg, edge = (0, 0, 0, 255), (255, 255, 255, 255)
        width = max(OUTLINE_ON_ART, lay.font_size // 7) if needs_halo \
            else max(OUTLINE_IN_BUBBLE, lay.font_size // 14)
    return fg, edge, width


# --------------------------------------------------------- the box sheet
#
# The page with the boxes drawn onto it, as a file. lee: "add a button n in the
# export that allow me to export the picture with the boxes".
#
# It is a copy of what the editor already draws on screen, and the point of it
# is that it looks the SAME — a sheet you can hand to somebody, print, or put
# beside the editor while you work through a chapter is worth nothing if its
# colours mean something different from the ones on screen. So these four
# colours are the four in `static/js/frames.js`, and a test parses that file
# and fails if the two ever drift apart.
# Three families, and the shades a sub-type of each may be — see kinds.py.
# There used to be six unrelated colours here for six flat types.
KIND_COLOURS = dict(_kinds.FAMILY_COLOUR)
# One colour for every linked pair, not one per group.
# lee: *"make the lunks just one color so all the link shoud be one color"*.
# Six link colours meant six more things on the page competing with the six
# text-type colours, and which link was which was never the question — the
# question is only ever "are these two joined".
LINK_COLOUR = "#2a63d8"
# The colours a sub-type may take, per family. Kept as one flat list as well,
# because the box sheet only ever asks "is this a colour we issue".
CUSTOM_PALETTE = [c for f in _kinds.FAMILIES for c in _kinds.family_shades(f)]

# The three alphas the stylesheet uses: `.box{background:kc+'22'}` is 0x22/255,
# `.gbox` is 6%, and `.bhint`'s border is kc+'88'.
BOX_FILL = 0x22 / 255.0
GROUP_FILL = 0.06
HINT_INK = 0x88 / 255.0
HINT_MIN = 1.25          # a balloon is only worth drawing when it is this much
                         # bigger than the writing — same test as frames.js


def _bgr(hexstr: str) -> tuple[int, int, int]:
    rgb = hex_rgb(hexstr) or (136, 136, 136, 255)
    return (rgb[2], rgb[1], rgb[0])


def kind_colour(kind: str, custom=()) -> str:
    """The colour of a text type: one definition, in kinds.py."""
    return _kinds.kind_colour(kind, custom)


def link_colour(group: int = 1) -> str:
    return LINK_COLOUR


def contrast_text(hexstr: str) -> tuple[int, int, int]:
    """Black or white on a given colour, whichever reads — frames.js's sum."""
    r, g, b, _ = hex_rgb(hexstr) or (136, 136, 136, 255)
    return (22, 22, 22) if (0.299 * r + 0.587 * g + 0.114 * b) > 150 \
        else (255, 255, 255)


class _Ink:
    """One transparent sheet to draw all the furniture on, composited once.

    Every piece of this has its own opacity — a 13% fill, a half-lit dashed
    balloon, a solid border — and blending each one against the page as it is
    drawn would tint whatever was drawn before it. So colour goes on one layer,
    opacity on another, and the page is touched exactly once at the end.
    """

    def __init__(self, img):
        self.out = img
        self.col = np.zeros(img.shape, np.float32)
        self.a = np.zeros(img.shape[:2], np.float32)

    def _stamp(self, mask, colour, alpha):
        m = mask > 0
        if not m.any():
            return
        self.col[m] = np.asarray(colour, np.float32)
        self.a[m] = np.maximum(self.a[m], float(alpha))

    def rect(self, box, colour, alpha, thickness=-1, dash=0):
        x, y, w, h = (int(round(v)) for v in box)
        m = np.zeros(self.a.shape, np.uint8)
        if dash:
            self._dashes(m, x, y, w, h, thickness or 1, dash)
        else:
            cv2.rectangle(m, (x, y), (x + w - 1, y + h - 1), 255, thickness)
        self._stamp(m, colour, alpha)

    @staticmethod
    def _dashes(m, x, y, w, h, th, dash):
        x1, y1 = x + w - 1, y + h - 1
        for i in range(x, x1, dash * 2):
            j = min(i + dash, x1)
            cv2.line(m, (i, y), (j, y), 255, th)
            cv2.line(m, (i, y1), (j, y1), 255, th)
        for i in range(y, y1, dash * 2):
            j = min(i + dash, y1)
            cv2.line(m, (x, i), (x, j), 255, th)
            cv2.line(m, (x1, i), (x1, j), 255, th)

    def line(self, a, b, colour, alpha, thickness, dash=0):
        m = np.zeros(self.a.shape, np.uint8)
        if not dash:
            cv2.line(m, a, b, 255, thickness, cv2.LINE_AA)
        else:
            (ax, ay), (bx, by) = a, b
            length = float(np.hypot(bx - ax, by - ay)) or 1.0
            step = dash * 2 / length
            t = 0.0
            while t < 1.0:
                t2 = min(1.0, t + dash / length)
                cv2.line(m, (int(ax + (bx - ax) * t), int(ay + (by - ay) * t)),
                         (int(ax + (bx - ax) * t2), int(ay + (by - ay) * t2)),
                         255, thickness, cv2.LINE_AA)
                t += step
        self._stamp(m, colour, alpha)

    def text(self, s, org, colour, scale, thickness):
        m = np.zeros(self.a.shape, np.uint8)
        cv2.putText(m, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, 255,
                    thickness, cv2.LINE_AA)
        self._stamp(m, colour, 1.0)

    def finish(self):
        a = self.a[:, :, None]
        return (self.out.astype(np.float32) * (1.0 - a)
                + self.col * a).round().clip(0, 255).astype(np.uint8)


def box_sheet(img, records, custom_kinds=()) -> np.ndarray:
    """The page with its boxes, numbers, balloons and links drawn on.

    `records` are the stored region dicts — the same ones the browser is sent —
    so this needs no masks, no cleaning and no typesetting, and costs one image
    copy per page. Nothing here is a step of the pipeline: it is a picture of
    what was found, for checking and for showing somebody.
    """
    out = img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    out = out.copy()
    H, W = out.shape[:2]
    ink = _Ink(out)
    recs = [r for r in (records or []) if r.get("bbox") or r.get("bubble_bbox")]

    def box_of(r):
        return [int(v) for v in (r.get("bbox") or r.get("bubble_bbox"))]

    def balloon_of(r):
        return [int(v) for v in (r.get("bubble_bbox") or r.get("bbox"))]

    # Two sections of one balloon wear a single frame round the pair, and their
    # own boxes go dashed and quiet inside it — the balloon is the thing that
    # is one, and the sections are the things you pick.
    groups: dict[int, list] = {}
    for r in recs:
        g = int(r.get("box_group") or 0)
        if g > 0:
            groups.setdefault(g, []).append(r)
    groups = {g: m for g, m in groups.items() if len(m) > 1}
    sectioned = {id(r) for m in groups.values() for r in m}

    for g, mem in sorted(groups.items()):
        xs = [balloon_of(r) for r in mem]
        x0 = min(b[0] for b in xs); y0 = min(b[1] for b in xs)
        x1 = max(b[0] + b[2] for b in xs); y1 = max(b[1] + b[3] for b in xs)
        col = _bgr(kind_colour(mem[0].get("kind", "bubble"), custom_kinds))
        ink.rect((x0, y0, x1 - x0, y1 - y0), col, GROUP_FILL)
        ink.rect((x0, y0, x1 - x0, y1 - y0), col, 1.0, thickness=2)

    # The balloon used to be drawn here too, faint and dashed behind the
    # writing. It went with the editor's `.bhint` on 2026-07-30 — lee: *"there a
    # thin dahed red box around the box around the text what does it do and
    # remove it"*. The exported sheet shows what the editor shows, so it shows
    # one rectangle per box as well. HINT_INK / HINT_MIN are kept because the
    # sheet's other opacities are checked against them.

    for r in recs:
        col = _bgr(kind_colour(r.get("kind", "bubble"), custom_kinds))
        b = box_of(r)
        weak = (float(r.get("confidence") or 0) < 0.55
                and not r.get("manual"))
        ink.rect(b, col, BOX_FILL)
        ink.rect(b, col, 1.0, thickness=2,
                 dash=6 if (id(r) in sectioned or weak) else 0)

    # A line split across two balloons: the connector runs between the middles
    # of the WRITING, and never between two sections of one balloon, which the
    # group frame has already said.
    links: dict[int, list] = {}
    for r in recs:
        g = int(r.get("link") or 0)
        if g > 0:
            links.setdefault(g, []).append(r)
    for g, mem in sorted(links.items()):
        if len(mem) < 2:
            continue
        mem = sorted(mem, key=lambda r: int(r.get("order") or 0))
        col = _bgr(link_colour(g))
        for a, b in zip(mem, mem[1:]):
            ga, gb = int(a.get("box_group") or 0), int(b.get("box_group") or 0)
            if ga > 0 and ga == gb:
                continue
            pa, pb = box_of(a), box_of(b)
            ink.line((pa[0] + pa[2] // 2, pa[1] + pa[3] // 2),
                     (pb[0] + pb[2] // 2, pb[1] + pb[3] // 2),
                     col, 0.9, max(2, min(H, W) // 400), dash=7)

    # The reading-order numbers, in their own pass so a numbered corner is
    # never buried under an overlapping neighbour's fill.
    tag = max(15, int(round(min(H, W) / 52.0)))
    scale = cv2.getTextSize("8", cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0][1]
    scale = (tag - 7) / float(scale or 1)
    for r in recs:
        s = str(int(r.get("order") or 0) + 1)
        (tw, th), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
        bw, bh = tw + 9, th + 8
        x, y = box_of(r)[:2]
        x = max(0, min(x - bh // 2, W - bw))
        y = max(0, min(y - bh // 2, H - bh))
        col = kind_colour(r.get("kind", "bubble"), custom_kinds)
        ink.rect((x, y, bw, bh), _bgr(col), 1.0)
        ink.text(s, (x + 4, y + bh - 5), contrast_text(col), scale, 2)

    return ink.finish()


READER_CSS = """
body{margin:0;background:#14151a;color:#e8e6e3;font:15px/1.55 -apple-system,
 BlinkMacSystemFont,'Segoe UI',sans-serif}
.wrap{display:flex;gap:22px;align-items:flex-start;padding:22px;max-width:1500px;
 margin:0 auto}
.pane-img{flex:0 0 58%;position:relative}
.pane-img img{width:100%;display:block;border-radius:6px}
.hot{position:absolute;border:2px solid rgba(255,196,0,.0);border-radius:8px;
 cursor:pointer;transition:.12s}
.hot:hover,.hot.on{border-color:#ffc400;background:rgba(255,196,0,.13)}
.lines{flex:1;min-width:280px}
.line{padding:11px 13px;margin-bottom:9px;border-radius:8px;background:#1e2027;
 border-left:3px solid #2f3441;cursor:pointer;transition:.12s}
.line:hover,.line.on{background:#262a34;border-left-color:#ffc400}
.n{display:inline-block;min-width:22px;color:#ffc400;font-weight:700}
.ja{color:#8b93a7;font-size:13px;margin-top:5px}
.sp{color:#6f7788;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.flag{color:#ff7a6b;font-size:12px;margin-top:4px}
h1{font-size:16px;padding:22px 22px 0;margin:0;font-weight:600}
"""

READER_JS = """
const link=(a,b)=>{a.addEventListener('mouseenter',()=>{a.classList.add('on');
b.classList.add('on');b.scrollIntoView({block:'nearest',behavior:'smooth'})});
a.addEventListener('mouseleave',()=>{a.classList.remove('on');
b.classList.remove('on')})};
document.querySelectorAll('.hot').forEach(h=>{
 const l=document.getElementById('l'+h.dataset.i);link(h,l);link(l,h)});
"""


def render_reader(page: Page, image_src: str, out_path: str) -> str:
    """Side-by-side HTML: original page, hoverable bubbles, ordered translations.

    Useful on its own as a language-learning tool, and it validates detection,
    OCR, ordering and translation without inpainting or typesetting.
    """
    hots, lines = [], []
    for r in page.ordered():
        x, y, w, h = r.bubble_bbox or r.bbox
        hots.append(
            f'<div class="hot" data-i="{r.order}" style="left:{x / page.w:.4%};'
            f'top:{y / page.h:.4%};width:{w / page.w:.4%};'
            f'height:{h / page.h:.4%}"></div>'
        )
        sp = f'<div class="sp">{html.escape(r.speaker)}</div>' if r.speaker else ""
        fl = f'<div class="flag">{html.escape(r.flagged)}</div>' if r.flagged else ""
        lines.append(
            f'<div class="line" id="l{r.order}">{sp}'
            f'<span class="n">{r.order + 1}</span>'
            f'{html.escape(r.dst_text or "—")}'
            f'<div class="ja">{html.escape(r.src_text)}</div>{fl}</div>'
        )

    doc = (
        f"<!doctype html><meta charset='utf-8'><style>{READER_CSS}</style>"
        f"<h1>{html.escape(page.source_path)} — {len(page.regions)} regions</h1>"
        f"<div class='wrap'><div class='pane-img'>"
        f"<img src='{html.escape(image_src)}'>{''.join(hots)}</div>"
        f"<div class='lines'>{''.join(lines)}</div></div>"
        f"<script>{READER_JS}</script>"
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return out_path
