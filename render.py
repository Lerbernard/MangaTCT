"""Render the translated page, and the side-by-side reader (stage 1)."""
from __future__ import annotations

import re
import html

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from . import kinds as _kinds
from .models import Page
from .typeset import (OUTLINE_IN_BUBBLE, OUTLINE_ON_ART, RIM_KNEE, RIM_SLOW,
                      TypesetConfig, _font,
                      on_art,
                      default_font_path, em_dash_glyph, marks_in)


def style_of(region, override=None) -> dict:
    """Everything anybody has to say about how this block is drawn, in order.

    Three answers can exist for a colour or a rim width and they rank:

    1. **what somebody set** - `layout_override`. Always wins.
    2. **what the original was drawn with** - `layout_measured`, read off the
       artwork by `inkstyle`. Beats a rule of thumb, because it is not a guess.
    3. **the automatic choice** - which is not in here at all; it is the
       argument every caller passes alongside, and it is what is left when
       neither of the above has an answer.

    One function so the order is written down once. It was written down three
    times, in three functions that each read `layout_override` for themselves,
    and the day a second source of truth appeared that would have been three
    places to remember to change.

    **How much of the measurement a block may take depends on what it is** -
    see `measured_for`. The ranking above is the same for all of them; what
    changes is how much there is at level 2.

    `override` is for the one caller that has a hand edit which is not on the
    region yet: `editor._preview_layout`, answering "what would this look like
    if you kept it" while somebody drags a control. It used to work the
    colours out for itself - `hex_rgb(o.get("fg")) or fg`, three lines that
    knew nothing about `layout_measured` - so the measured style appeared on
    the page and vanished the moment a box was selected. lee: *"the changes
    ate only appkied when i select a box"*. One rule, one place, and a way in
    for the caller that has the answer early.
    """
    got = measured_for(region)
    ov = (getattr(region, "layout_override", None) if override is None
          else override)
    got.update({k: v for k, v in (ov or {}).items() if v not in (None, "")})
    return got


def hand_style(region, override=None) -> dict:
    """Level 1 alone: what somebody SET, with the measurement left out.

    `style_of` is the answer to "how is this drawn". This is the answer to a
    narrower question that only comes up in one place - *did a person say
    this, or did the measurement?* - and the two must not be confused, which
    is exactly what having one field for both used to cost (see
    `models.TextRegion.layout_measured`).

    `_hollow_colours` is the caller. Hollow overrules the fill and the rim,
    and it may overrule the automatic choice for them - but not a person.
    """
    ov = (getattr(region, "layout_override", None) if override is None
          else override)
    return {k: v for k, v in (ov or {}).items() if v not in (None, "")}


# The one sub-type that gets the whole measurement. `kinds.PRELOADED` calls it
# "Big / impact" and it is the case the measurement was built for: a sound the
# artist DREW, at a size where the way it is drawn is the point.
BIG_SOUND = "sfx_big"

# ...and what every other drawn sound may take: the LINE, and nothing about
# the palette. `rim` and `hollow` go with `stroke` because the three are one
# fact - how the letterform itself is made - and taking the width without the
# shape it belongs to would put a measured rim round a filled letter.
SHAPE_KEYS = ("stroke", "rim", "hollow")


def measured_for(region) -> dict:
    """How much of `layout_measured` this block is allowed to use.

    lee: *"the fimd formatting and copy it should only work for big sfx boxe,
    everything else shoud get teh white fill and black outine or teh inverse"*.

    He is right, and his own chapter says why. Measuring reads the ink the
    ORIGINAL letters were drawn in, which is the right answer for a drawn
    sound and the wrong one for a line of dialogue - because dialogue is
    replaced, not reproduced, and what it needs is to be READ:

    * `020.jpg` id6, free text on a dark panel, measured `#646464`. Mid-grey
      on near-black. lee's screenshot of it is barely legible.
    * `009.jpg` id4, a BLACK balloon with white Japanese in it, measured
      `#020202` with a `#ECECEC` keyline - black letters on black paper, so
      all that is left on the page is the outline.

    `_ink_colours` already knows the answer for those: *"a decidedly dark
    background always gets white typesetting with a black edge - the one thing
    lee has asked for every time this has come up."*

    So:

    * **a big drawn sound** takes all of it. Colours, keyline, glow, hollow.
    * **any other drawn sound** takes the LINE only - the rim width and
      whether the letterform is hollow. That half is not a palette, it is *a
      pen has a width*: `のびー` has a two-pixel rim and the rule of thumb put
      a fourteen-pixel one round STRETCH. lee, on losing that: it is the "it's
      too small" work, and it stays.
    * **everything else** - bubbles, narration, free text, asides, shouts -
      takes nothing, and gets the automatic readable pair.

    A hand override is not affected by any of this. Somebody who sets a colour
    on a bubble has said what they want, and `style_of` lays it over the top
    whatever this function returned.

    Asked with the module's own sub-type registry, and the failure mode is the
    safe one: with no registry loaded `family_of` calls an unknown sub-type a
    bubble, so the block takes NOTHING from the measurement and is typeset in
    the pair that can be read.
    """
    got = dict(getattr(region, "layout_measured", None) or {})
    if not got:
        return {}
    kind = getattr(region, "kind", "") or ""
    if kind == BIG_SOUND:
        return got
    if _kinds.family_of(kind) == "sfx":
        return {k: got[k] for k in SHAPE_KEYS if k in got}
    return {}


def stroke_for(region, automatic: int, override=None) -> int:
    """An outline width set by hand beats the automatic choice, and a MEASURED
    one beats it too.

    Both the colour pass and the drawing pass work this out independently, so
    the rule lives in one place - applying it in only one of them meant the
    control moved the preview and left the exported page alone.
    """
    ov = style_of(region, override)
    if ov.get("stroke") not in (None, ""):
        return max(0, min(30, int(ov["stroke"])))
    return int(automatic)


# NO FILL AT ALL: letters drawn as their outline and nothing inside them.
# lee: *"can you add a trnsparent option in the color picker for the fill,
# wher its a white box with ared kine trought it diagonhaly"*.
#
# `#rrggbbaa` rather than a word like "none" or a flag beside the colour,
# because it needs no new field and no new question anywhere it travels: it is
# a colour, it goes in the same box, it comes back through the same parser,
# and everything that draws with it already works in RGBA.
#
# It is NOT `hollow`. Hollow says "the rim IS the letterform", and takes its
# colour from the ink for that reason (`_hollow_colours`). Somebody who empties
# the fill by hand has said nothing about the outline, and theirs stays theirs.
NO_FILL = "#00000000"


def any_rgb(s):
    """A colour in EITHER spelling this app writes, as (r, g, b, a).

    `hex_rgb` reads the stored one - `#rrggbb`, and `#rrggbbaa` for a fill that
    is not there. The browser is sent the other one: `editor._css_rgba` writes
    `rgba(r,g,b,a)` because the preview drops these straight into `color` and
    `-webkit-text-stroke`, and a layout that has been through a save carries
    that spelling in `layout.fg`.

    Reading only the first was a real bug and a quiet one: `auto_halo` asks
    "does this block have a fill", the record said `rgba(0,0,0,0)`, `hex_rgb`
    said "not a colour", and the halo the exported page drew never reached the
    editor. Anything that asks a QUESTION about a colour has to read both
    spellings; anything that stores one still writes hex.
    """
    got = hex_rgb(s)
    if got is not None:
        return got
    if not isinstance(s, str):
        return None
    m = re.match(r"^\s*rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*"
                 r"(?:,\s*([0-9.]+)\s*)?\)\s*$", s)
    if not m:
        return None
    a = 255 if m.group(4) is None else int(round(float(m.group(4)) * 255))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
            max(0, min(255, a)))


def hex_rgb(s):
    """'#rrggbb' -> (r, g, b, 255), or None if it is not a colour.

    `#rrggbbaa` too, which is how an emptied fill travels - see `NO_FILL`. The
    two lengths and nothing else: a three-digit shorthand would be a second
    spelling of a colour this app never writes, and every place that compares
    one stored colour against another would have to learn about it.
    """
    if not isinstance(s, str):
        return None
    s = s.strip().lstrip("#")
    if len(s) not in (6, 8):
        return None
    try:
        n = int(s, 16)
    except ValueError:
        return None
    if len(s) == 8:
        return ((n >> 24) & 255, (n >> 16) & 255, (n >> 8) & 255, n & 255)
    return ((n >> 16) & 255, (n >> 8) & 255, n & 255, 255)


def _lit(c):
    """A colour that actually shows - or None.

    `NO_FILL` (an eight-digit hex with a zero alpha) is how the panel's ×
    says *this effect is OFF here* in a place where an empty field would
    mean *inherit* - a RANGE whose block has the effect. Everything that
    asks "is this effect on" goes through this, so a transparent shadow or
    a transparent gradient endpoint is an effect that is off, not an
    effect drawn invisibly (or, worse, a ramp fading to nothing)."""
    return c if (c and c[3]) else None


def colours_for(region, fg, edge, override=None):
    """Text and outline colours set by hand beat the automatic choice.

    **The edge follows the fill.** `_ink_colours` never picks the two apart:
    it decides which way round the page is and hands back a PAIR, white on
    black or black on white, and says so - *"the edge is the opposite
    colour"*. Take one of the pair from the override and leave the other as it
    was and the invariant is gone.

    It is not a hypothetical. `inkstyle.measure_page` writes a measured `fg`
    for every region it can read and an `edge` only where it actually found an
    outline, so a box whose original had no keyline gets the measured fill and
    the automatic edge - and on lee's page 001 those are BOTH BLACK. `ザブン`
    would have come back as black letters inside an eleven-pixel black rim: a
    blob. The pair has to stay a pair.

    So: an edge nobody set is turned over when it would be INVISIBLE against
    the fill, and only then. Not "the edge always follows the fill" - that was
    the first version and it is too much. Somebody who picks a red fill by
    hand and leaves the halo alone has changed nothing about what is behind
    the letters, and the halo's job is to hold them off it; overruling that
    would move a decision they did not make. The narrow rule fixes the blob
    and leaves every other hand choice exactly where it was.

    Name both and both are yours, whatever they are - two colours a hair apart
    is a thing somebody may want, and only they can say so.
    """
    ov = style_of(region, override)
    mine, theirs = hex_rgb(ov.get("fg")), hex_rgb(ov.get("edge"))
    out_fg, out_edge = (mine or fg), (theirs or edge)
    # An EMPTIED fill has nothing to be invisible against, and the outline is
    # the only thing left on the page - turning it over would be turning over
    # the whole of what somebody asked for. See `NO_FILL`.
    if out_fg[3] == 0:
        return out_fg, out_edge
    if mine is not None and theirs is None and _same_ink(out_fg, out_edge):
        # Mid-grey counts as dark: an edge holds the letters off whatever is
        # behind them, and white does that against more of a manga page.
        out_edge = ((255, 255, 255, 255) if sum(out_fg[:3]) < 384
                    else (0, 0, 0, 255))
    return out_fg, out_edge


# How near two colours have to be before one of them stops being an outline
# round the other. Generous on purpose: `#020202` against `#000000` is two
# levels apart and there is no rim on the page at all, and nothing between
# that and a rim you can see wants to be called one.
SAME_INK = 40


def _same_ink(a, b) -> bool:
    return max(abs(int(x) - int(y)) for x, y in zip(a[:3], b[:3])) < SAME_INK


def _draw_stamp(d, cx, y, adv, glyph, fill=None, stroke_width=0,
                stroke_fill=None, **_):
    """One character the font could not draw, stamped as a bitmap.

    `glyph` is (advance, top, mask) - an em-dash from `typeset.em_dash_glyph`
    or a mark from `typeset.mark_glyph`, which return the same tuple for this
    reason. The mask goes through ImageDraw.bitmap, so it takes the TEXT
    COLOUR rather than being painted black: a mark on a dark panel is white
    like the letters beside it. The outline is the same mask grown by the
    stroke width and stamped underneath, so a heart gets the halo every other
    character on the page gets.
    """
    _, top, mask = glyph
    x = int(round(cx + (adv - mask.width) / 2.0))
    yy = int(round(y + top))
    if stroke_width and stroke_fill is not None:
        sw = int(stroke_width)
        grown = ImageOps.expand(mask, border=sw, fill=0)
        grown = grown.filter(ImageFilter.MaxFilter(2 * sw + 1))
        d.bitmap((x - sw, yy - sw), grown, fill=stroke_fill)
    d.bitmap((x, yy), mask, fill=fill)


def arc_places(line, f, lspace, curve, x, y, kind="arch"):
    """Where each letter of a curved line sits, and how far it is turned.

    A curved line is the same letters with the same advances, walked along a
    SHAPE instead of a straight baseline, and `kind` says which shape:

    * `arch` (the original, and the default): a circle. `curve` is the whole
      angle the line subtends, in degrees, so it means the same thing
      whatever the words are or how big they are: 60 is the same bend on
      "OH" as on "OH NO, LOOK OUT". Positive arches up like a rainbow - the
      middle is highest - and negative sags. R = length / angle.
    * `wave`: one S along the line - up then down for a positive `curve`,
      the other way for a negative one. `curve` is the STEEPEST the wave
      gets, in degrees, so the same number means the same visible lean on a
      short shout and a long one; the letters turn with the tangent.
    * `rise`: the baseline climbs in a straight slant (`curve` degrees,
      negative falls) and the letters stay UPRIGHT - which is what tells a
      rise apart from simply rotating the block.

    Returns [(cx, cy, degrees, char, advance)], one per character, with the
    centre of each letter's advance on the shape and the tangent there. The
    same arithmetic is in `typesetting.js` (`arcPlaces`), and a test
    compares the two, kind by kind.
    """
    import math
    widths = [f.getlength(ch) for ch in line]
    total = sum(widths) + lspace * max(0, len(line) - 1)
    kind = str(kind or "arch")
    if kind in ("wave", "rise"):
        # capped short of vertical: tan() runs away long before 90, and a
        # slope past 75 degrees is letters on top of one another anyway
        d = max(-75.0, min(75.0, float(curve or 0)))
        if total <= 0 or abs(d) < 1e-4:
            return None
        slope0 = math.tan(math.radians(d))
        out = []
        s = -total / 2.0
        for ch, wd in zip(line, widths):
            u = s + wd / 2.0
            t = (u + total / 2.0) / total
            if kind == "wave":
                # amplitude from the slope cap: max |dy/dx| of A*sin(2*pi*t)
                # over one period is A*2*pi/total
                A = total * slope0 / (2.0 * math.pi)
                cy = y - A * math.sin(2.0 * math.pi * t)
                deg = math.degrees(math.atan(
                    -slope0 * math.cos(2.0 * math.pi * t)))
            else:
                cy = y - u * slope0
                deg = 0.0
            out.append((x + u, cy, deg, ch, wd))
            s += wd + lspace
        return out
    ang = math.radians(float(curve))
    if total <= 0 or abs(ang) < 1e-4:
        return None
    R = total / ang                     # signed: the sign is the direction
    # The bend has to keep the line where the fitter put it. Hung from the
    # middle, an arch sinks by its whole sagitta - at 140 degrees that is a
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
    the line's middle - the same anchor the straight path draws from. Measuring
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
    # an ascender - anchoring at (pad, pad) itself drew every capital off the
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
    turned, and stamped through `ImageDraw.bitmap` - which takes a colour, so
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
            # round with it - rotate the offset, then place the turned mask
            mid = (ox + gw / 2.0, oy + gh / 2.0)
            m = m.rotate(-deg, resample=Image.BICUBIC, expand=True)
            a = math.radians(deg)
            rx = mid[0] * math.cos(a) - mid[1] * math.sin(a)
            ry = mid[0] * math.sin(a) + mid[1] * math.cos(a)
            d.bitmap((int(round(cx + rx - m.width / 2.0)),
                      int(round(cy + ry - m.height / 2.0))), m,
                     fill=(stroke_fill if do_stroke else fill))


def draw_line(d, x, y, line, f, lspace=0.0, curve=0.0, ckind="arch", **kw):
    """One line of text, centred at (x, y), with optional letter spacing.

    An em-dash is drawn by hand when the font has no glyph for it, so comic
    faces that ship only a hyphen still show a real long dash - and so is a
    MARK in the line: a heart, a star, a music note, a sweat drop. See
    `typeset.mark_glyph` for where the shape comes from, and for the
    measurement that makes it necessary - of the sixteen faces this app ships,
    the speech face has not one of them."""
    path, px = getattr(f, "path", "") or "", int(getattr(f, "size", 0))
    bar = em_dash_glyph(path, px) if "—" in line else None
    # {char: (advance, top, mask)}. The dash uses the same tuple, so it joins
    # the same table rather than keeping a branch of its own - two drawing
    # paths for one idea is two places for it to go wrong.
    stamps = dict(marks_in(line, path, px)) if line else {}
    if bar:
        stamps["—"] = bar
    if curve:
        places = arc_places(line, f, lspace, curve, x, y, kind=ckind)
        if places:
            # A stamped mark is a bitmap rather than a glyph, so a curved line
            # falls back to the font's own character for it. Nobody curves a
            # line of dashes; losing the curve on the whole line is worse.
            _draw_curved(d, places, f, bar=bar, **kw)
            return
    if not lspace and not stamps:
        d.text((x, y), line, font=f, anchor="mm", **kw)
        return
    widths = [(stamps[ch][0] if ch in stamps else f.getlength(ch))
              for ch in line]
    total = sum(widths) + lspace * max(0, len(line) - 1)
    cx = x - total / 2.0
    for ch, wd in zip(line, widths):
        if ch in stamps:
            _draw_stamp(d, cx, y, wd, stamps[ch], **kw)
        else:
            d.text((cx, y), ch, font=f, anchor="lm", **kw)
        cx += wd + lspace


def _gradient_image(size, bbox, c0, c1, angle_deg):
    """A full-size RGBA image blending c0 -> c1 across bbox.

    angle 0 runs top to bottom, 90 left to right, and so on clockwise -
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
    # Colours are read off the artwork, so a page with no artwork to read -
    # a stand-in built to exercise the fitter alone - simply keeps whatever
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
        lay.fg = _css(fg)
        lay.edge = _css(edge)
        lay.stroke = int(stroke)


def _css(c) -> str:
    """A colour the way the browser will read it back.

    Six digits, and EIGHT when there is an alpha to carry. `render_page` draws
    from `colours_for` and never looks at these, so an emptied fill exported
    correctly while `lay.fg` said `#000000` - and `lay.fg` is what the preview
    and the panel read. The block came out hollow on the page and solid black
    on screen, which is the one thing this field exists to prevent.
    """
    r, g, b = c[:3]
    a = c[3] if len(c) > 3 else 255
    return ("#%02x%02x%02x" % (r, g, b)) + ("" if a >= 255 else "%02x" % a)




# The style keys a SPAN may carry.
#
# Most of them are PAINT: they put different colours on the same glyphs in
# the same places. `font` and `font_size` are not - they change how much
# room the words take. The distinction used to decide how the line was
# DRAWN (whole-line copies cut into bands for paint, a flow for metrics);
# it no longer does, because a band is a box behind the letter and cutting
# one slices the glyph beside it. Every span is laid out RUN BY RUN now,
# the way any text engine sets mixed type. See `flow_runs`.
#
# What the distinction still decides is whether the LAYOUT has to be redone
# when a span changes: a colour cannot move a word, a size can. See
# `METRIC_KEYS` and `has_metric_spans`. lee: *"the changing size and fonts
# happens to teh whole etxt box instead fo just the selevcted text"*.
SPAN_KEYS = ("fg", "edge", "stroke", "fg1", "fg2", "grad_angle",
             "edge1", "edge2", "edge_angle", "glow", "glow_size",
             "iglow", "iglow_size", "shadow", "sh_dist", "sh_blur",
             "opacity", "font", "font_size")

# The two that change the METRICS - which is what decides whether a line can
# be cut into bands or has to be flowed.
METRIC_KEYS = ("font", "font_size")


def _spans_of(r, lay):
    """[(start, end, {style}), ...] over the flat text of the laid-out
    lines (`"\n".join(lines)` - a line break counts one character, which
    is also what a wrap that turns a space into a break costs)."""
    ov = getattr(r, "layout_override", None) or {}
    raw = ov.get("spans") or []
    if not isinstance(raw, list):
        return []
    n = sum(len(ln) for ln in lay.lines) + max(0, len(lay.lines) - 1)
    out = []
    for sp in raw[:200]:
        if not isinstance(sp, dict):
            continue
        try:
            s0, e0 = int(sp.get("s")), int(sp.get("e"))
        except (TypeError, ValueError):
            continue
        st = sp.get("st") or {}
        if not isinstance(st, dict):
            continue
        s0, e0 = max(0, s0), min(n, e0)
        keep = {k: st[k] for k in SPAN_KEYS if st.get(k) not in (None, "")}
        if e0 > s0 and keep:
            out.append((s0, e0, keep))
    return out


def _prefix_cuts(line, f, lspace):
    """x of every glyph boundary from the line's left edge - the same two
    metric modes `draw_line` draws by, so a cut falls exactly between the
    glyphs the renderer put there (kerned when the drawing is kerned)."""
    path, px = getattr(f, "path", "") or "", int(getattr(f, "size", 0))
    stamps = dict(marks_in(line, path, px)) if line else {}
    if "—" in line:
        g = em_dash_glyph(path, px)
        if g:
            stamps["—"] = g
    if not lspace and not stamps:
        return [f.getlength(line[:i]) for i in range(len(line) + 1)]
    widths = [(stamps[ch][0] if ch in stamps else f.getlength(ch))
              for ch in line]
    cuts = [0.0]
    run = 0.0
    for i, wd in enumerate(widths):
        run += wd + (lspace if i < len(widths) - 1 else 0.0)
        cuts.append(run)
    return cuts


def has_metric_spans(spans) -> bool:
    """Does any range change how much room the words take? That is the one
    question that decides between the two ways a spanned block is drawn."""
    return any(k in st for _s, _e, st in spans for k in METRIC_KEYS)


def _run_font(ov, st, lay, cfg_path=""):
    """The face and size ONE RUN is set in - the block's, with the range's
    own choices laid over it."""
    path = (st.get("font") or ov.get("font")
            or lay.font_path or cfg_path or "")
    size = st.get("font_size")
    try:
        size = int(round(float(size)))
    except (TypeError, ValueError):
        size = 0
    return _font(path, size or lay.font_size)


def _run_width(text, f, lspace):
    """How wide one run is, measured the way `draw_line` draws it - marks
    and the hand-drawn em dash included."""
    return _prefix_cuts(text, f, lspace)[-1] if text else 0.0


def flow_runs(r, lay, f, ov, spans, cfg_path=""):
    """[(style_overlay, [(cx, cy, text, font), ...]), ...] - the block laid
    out RUN BY RUN. This is how EVERY spanned block is drawn.

    The other way was to paint the whole line once per style and cut the
    copies into vertical strips at the glyph boundaries. It was used for
    every span that did not change the metrics, and it is gone: a letter's
    ink is not inside its advance box, so a vertical cut slices through the
    glyph beside it and leaves a letter with a hard seam down it, half in
    each colour. lee named it exactly - *"it shoud apply to the letter it
    self and not a box behiod teh letter"*.

    So the line is set the way any text engine sets mixed type: run after
    run, each in its own metrics, all of them sharing one baseline, the
    whole line centred on the origin the fitter chose. Each run only ever
    draws its own characters, so a style cannot land on a character that
    does not carry it - at any precision, in any face.

    The baseline is placed so the line's ink box - the tallest ascender over
    the deepest descender across the runs - is centred on that origin, which
    for a line of one run is exactly where PIL's `mm` anchor already puts
    it. So a block nobody has resized comes out pixel for pixel as before.
    `drawText` does the same thing with `align-items:baseline`.
    """
    import json as _json
    lsp = float(ov.get("lspace") or 0.0)
    crv = float(ov.get("curve") or 0.0)
    ckd = str(ov.get("curve_kind") or "arch")
    out = {}
    order = []
    off = 0
    for (ox, oy), line in zip(lay.line_origins, lay.lines):
        if not line:
            off += 1
            continue
        # one run per stretch of constant effective style
        keys, sts = [], []
        for i in range(len(line)):
            st = {}
            for s0, e0, sst in spans:
                if s0 <= off + i < e0:
                    st.update(sst)
            keys.append(_json.dumps(st, sort_keys=True) if st else "")
            sts.append(st)
        runs = []
        s = 0
        for i in range(1, len(line) + 1):
            if i < len(line) and keys[i] == keys[s]:
                continue
            runs.append((s, i, keys[s], sts[s]))
            s = i
        # A CURVED line is placed by the arc, not by the walk below - the
        # same `arc_places` the unspanned path uses, in the block's own
        # face, so a paint span cannot move a letter. (The browser does the
        # same: its curved branch measures every advance in the block's
        # metrics and paints each letter in its span's colours, so a range
        # that changes the SIZE or FACE deliberately does not resize a
        # curved letter on either side. A curve is one arc through one
        # line; two sizes on it would be two different arcs.)
        if crv:
            places = arc_places(line, f, lsp, crv, ox, oy, kind=ckd)
            if places:
                for a, b, kk, st in runs:
                    if kk not in out:
                        out[kk] = (st, [])
                        order.append(kk)
                    out[kk][1].append((ox, oy, line[a:b], f, places[a:b]))
                off += len(line) + 1
                continue
        fonts = [_run_font(ov, st, lay, cfg_path) for _a, _b, _k, st in runs]
        widths = [_run_width(line[a:b], ff, lsp)
                  for (a, b, _k, _st), ff in zip(runs, fonts)]
        # each run's own width already carries the gaps INSIDE it, so what
        # is left to add is one gap at each seam between runs
        total = sum(widths) + lsp * max(0, len(runs) - 1)
        mets = [ff.getmetrics() for ff in fonts]
        top = max(m[0] for m in mets)
        bot = max(m[1] for m in mets)
        base_y = oy - (top + bot) / 2.0 + top
        cx = ox - total / 2.0
        for (a, b, kk, st), ff, wd, (asc, desc) in zip(runs, fonts, widths,
                                                       mets):
            # `draw_line` centres on the middle of the run's own
            # ascender-to-descender box, so the y that puts its baseline on
            # the line's is that middle.
            mid = base_y + (desc - asc) / 2.0
            if kk not in out:
                out[kk] = (st, [])
                order.append(kk)
            out[kk][1].append((cx + wd / 2.0, mid, line[a:b], ff, None))
            cx += wd + lsp
        off += len(line) + 1
    return [(out[k][0], out[k][1]) for k in order if out[k][1]]


def _ink_layer(size_wh, r, lay, f, ov, fg, edge, stroke, pieces=None):
    """Everything one STYLE paints for a block - shadow, glow, letters,
    both gradients, inner glow - on one transparent layer.

    Factored out of `render_page` so a block whose text carries SPANS - a
    word restyled by itself, Photoshop-fashion (lee: *"allow teh user to
    modify spesifuica part of a text box"*) - can be painted once per
    distinct style and composited through per-run masks. A block with no
    spans calls it exactly once, which is the old body verbatim.

    `pieces` is WHAT TO DRAW: [(centre x, middle y, text, font, arc)].
    `arc` is None for a straight piece; on a curved block it is the
    piece's slice of the line's `arc_places`, one (x, y, degrees, char,
    advance) per letter. It
    defaults to the block's own lines in the block's own face, which is
    what a block with no spans passes. A block that carries spans passes
    the runs of ONE style instead, each already placed by `flow_runs`, and
    calls this once per style - so a style's glow and its shadow are
    composited once, over its own characters and no others.
    """
    # `style_of` was read by the caller; `ov` is that style, or that style
    # with one span's choices laid over it.
    if pieces is None:
        pieces = [(x, y, line, f, None)
                  for (x, y), line in zip(lay.line_origins, lay.lines)]
    layer = Image.new("RGBA", size_wh, (0, 0, 0, 0))
    lsp = float(ov.get("lspace") or 0.0)
    # How far the line bends: degrees of arc across the whole line -
    # and which SHAPE it bends along. See `arc_places`.
    crv = float(ov.get("curve") or 0.0)
    ckd = str(ov.get("curve_kind") or "arch")

    def _stamp(dd, x, y, text, ff, pl, dx=0.0, dy=0.0, **kw):
        """One piece, wherever it goes. A straight piece is a line (or a
        run already placed on the shared baseline); a curved piece carries
        its own slice of the line's arc, each letter with its place and
        its turn, so a RANGE's colours land on curved letters exactly
        where the unspanned arc puts them."""
        if pl is not None:
            _draw_curved(dd, [(cx + dx, cy + dy, dg, ch, ad)
                              for cx, cy, dg, ch, ad in pl], ff, **kw)
        else:
            # `crv` passes through untouched. A whole-line piece (a block
            # with no spans) is entitled to its arc; a RUN from
            # `flow_runs` only ever arrives without an arc of its own
            # when the block is straight, so crv is 0 there by
            # construction - a curved block's runs all carry `pl`.
            draw_line(dd, x + dx, y + dy, text, ff, lsp, crv, ckind=ckd,
                      **kw)

    shcol = _lit(hex_rgb(ov.get("shadow")))
    if shcol:
        dist = float(ov.get("sh_dist") if ov.get("sh_dist")
                     not in (None, "") else 2)
        blur = float(ov.get("sh_blur") if ov.get("sh_blur")
                     not in (None, "") else 3)
        offx, offy = dist * 0.707, dist * 0.707
        # The same mask-not-picture rule as the glow below: blurring a
        # coloured stamp on a transparent (black) sheet fringes its edge
        # towards black. Invisible on the usual black shadow, a dark rim on
        # any light one - so the shape is blurred as an L mask and coated
        # in the colour once.
        sm = Image.new("L", size_wh, 0)
        ds = ImageDraw.Draw(sm)
        for x, y, line, ff, pl in pieces:
            _stamp(ds, x, y, line, ff, pl, dx=offx, dy=offy,
                   fill=255, stroke_width=stroke, stroke_fill=255)
        if blur > 0:
            sm = sm.filter(ImageFilter.GaussianBlur(blur))
        if shcol[3] < 255:
            sm = sm.point(lambda v, m=shcol[3]: v * m // 255)
        sh = Image.merge("RGBA", (*Image.new(
            "RGBA", size_wh, shcol).split()[:3], sm))
        layer = Image.alpha_composite(layer, sh)

    # An OUTER GLOW: the same letters, spread outwards and blurred, sitting
    # under everything. A shadow with no offset is not the same thing - a
    # glow has to be grown before it is blurred or it stays inside the
    # letters and never shows past the outline. So the silhouette is drawn
    # with a fat stroke (`spread`) and blurred by about half of it, and the
    # result is stacked so the halo is dense enough to read on artwork
    # rather than a grey breath. Photoshop's Size and Spread, in one knob.
    #
    # ON A LETTERFORM WITH NOTHING INSIDE IT the silhouette is the wrong
    # source. The glyph body is a hole - the page shows through it - and a
    # halo grown from the whole silhouette is a slab of colour behind that
    # hole, which is a filled letter in the glow's colour and not a glow
    # at all. lee: *"outer glow files teh whole thing while it shoud only
    # emit from the outline part of teh text"*.
    #
    # He has named the rule. The light comes off what is DRAWN, which on
    # this block is the rim, and an OUTER glow is the half of it that goes
    # outward - so the ring is grown and blurred like any other silhouette
    # and then cut back to the paper outside the letters. The half that
    # goes inward is a different effect with its own colour and its own
    # knob, and it is a few dozen lines below this one.
    hole = fg[3] == 0 and stroke > 0

    def _mask(width, fill, edge_on=255):
        """The letters as an L mask: the silhouette, or the ring alone."""
        m = Image.new("L", size_wh, 0)
        dm = ImageDraw.Draw(m)
        for x, y, line, ff, pl in pieces:
            _stamp(dm, x, y, line, ff, pl, fill=fill,
                   stroke_width=width, stroke_fill=edge_on)
        return m

    glcol = hex_rgb(ov.get("glow"))
    size = float(ov.get("glow_size") if ov.get("glow_size")
                 not in (None, "") else 6)
    if glcol is None:
        # ...or the light a letterform with nothing inside it gets on the
        # outside of its line. `fg` is transparent by now on such a block -
        # `_hollow_colours` has run - which is the test `auto_halo` makes.
        got = auto_glow(r, lay, fg, edge, ov)
        if got:
            glcol, size = got[0], float(got[1])
    if glcol and glcol[3]:
        if size > 0:
            spread = max(1, int(round(size)))
            # THE MASK IS BLURRED, NEVER THE PICTURE. The halo used to be
            # stamped in its colour onto a transparent sheet and the SHEET
            # blurred - and a transparent sheet is transparent BLACK.
            # PIL's Gaussian runs over each channel as it stands, so at
            # the halo's edge the colour blended towards that hidden black
            # while the alpha faded, and what reached the page was a soft
            # GREY RING hugging the outside of every glow - laid twice,
            # because a chosen glow goes on twice. The editor never showed
            # it (a browser blurs premultiplied), which is why it read as
            # an export-only fault. lee, with a crop of his EEEEK! page:
            # *"its on outer glow isusie and thsi si still happening"*.
            # Blurring the SHAPE as an L mask and marrying it to one flat
            # coat of the colour leaves no black for the edge to pick up.
            if hole:
                # the rim, grown
                a = _mask(stroke + 2 * spread, 0)
            else:
                a = _mask(stroke + spread, 255)
            a = a.filter(ImageFilter.GaussianBlur(size * 0.55))
            gl = Image.merge("RGBA", (*Image.new(
                "RGBA", size_wh, glcol).split()[:3], a))
            if hole:
                # ...and the glyph body punched back out AFTER the blur,
                # not before it. Before, the blur carries the halo straight
                # back over the hole it was just cut out of - at a size
                # worth setting, all the way across it, which is the solid
                # slab lee was looking at. The cut falls on the glyph
                # outline, which is the rim's own centre line, so the rim
                # covers it and there is no edge to see.
                gl.putalpha(ImageChops.multiply(
                    gl.split()[3], ImageChops.invert(_mask(0, 255))))
            # HOW MUCH OF IT THERE IS, which is the whole difference
            # between a light and a sticker.
            #
            # A glow somebody CHOSE is composited twice, because on
            # artwork one pass of a Gaussian is a grey breath. An
            # AUTOMATIC one is not asked for and must not shout: it comes
            # back from `auto_halo` with an alpha under full, and at that
            # strength one pass is the effect. Composited twice at full
            # alpha it was an opaque band six pixels wide round every
            # letter, which on a white page merged between the letters
            # into one black slab - measured against the preview and then
            # looked at, which is how it was caught.
            if glcol[3] < 255:
                gl.putalpha(gl.split()[3].point(
                    lambda v, m=glcol[3]: v * m // 255))
                layer = Image.alpha_composite(layer, gl)
            else:
                for _ in range(2):
                    layer = Image.alpha_composite(layer, gl)

    # THE LETTERS GO ON THEIR OWN SHEET AND ARE COMPOSITED.
    #
    # Drawing them straight onto the layer WRITES the pixels, and a fill
    # whose alpha is zero writes holes - so stamping a hollow block over
    # its own glow rubbed the glow out everywhere the glyph body covered,
    # and no effect underneath could ever reach the see-through middle.
    # Compositing puts nothing where there is nothing instead of taking
    # away what is there. A solid fill is unaffected: opaque over anything
    # is opaque.
    sheet = Image.new("RGBA", size_wh, (0, 0, 0, 0))
    ds = ImageDraw.Draw(sheet)
    # A GRADIENT OWNS ITS LETTERS, and the plain colour leaves no trace.
    # The letters used to be drawn in the plain colour and the ramp
    # pasted over them, so at the glyph mask's antialiased edge a dark
    # fill fringed a bright ramp - and the editor, which never paints
    # the plain colour under a gradient at all, showed no fringe: one
    # more place the two could disagree. lee: *"it should disable the
    # regular box and reove it from text and only keep the grediant ...
    # that was what was causing teh inconsoistenties"*. Drawn in the
    # ramp's START colour instead, the edge blends into the gradient
    # that is about to cover it. The same for the outline under its own
    # gradient.
    _has_g2 = _lit(hex_rgb(ov.get("fg2")))
    _has_e2 = _lit(hex_rgb(ov.get("edge2")))
    fill_ink = ((hex_rgb(ov.get("fg1")) or fg)
                if (_has_g2 and fg[3]) else fg)
    edge_ink = ((hex_rgb(ov.get("edge1")) or edge)
                if (_has_e2 and stroke > 0) else edge)
    for x, y, line, ff, pl in pieces:
        _stamp(ds, x, y, line, ff, pl, fill=fill_ink,
               stroke_width=stroke, stroke_fill=edge_ink)
    layer = Image.alpha_composite(layer, sheet)

    # ...and a second colour on the OUTLINE turns that into a gradient too.
    # lee: *"can you make it so that i can add gradient to the ouline of
    # the text"*.
    #
    # The mask is the ring and only the ring: drawn with the stroke lit and
    # the fill dark, so the glyph the stroke was drawn around is punched
    # back out of it. Painting through the whole stroked shape instead
    # would lay the outline's gradient across the letters as well, and then
    # the fill - its own colour or its own gradient - would be repainting
    # over the top of it, which is two answers to one question.
    edge2 = _lit(hex_rgb(ov.get("edge2")))
    if edge2 and stroke > 0:
        ring = Image.new("L", size_wh, 0)
        dr = ImageDraw.Draw(ring)
        for x, y, line, ff, pl in pieces:
            _stamp(dr, x, y, line, ff, pl, fill=0,
                   stroke_width=stroke, stroke_fill=255)
        rbox = ring.getbbox()
        if rbox:
            grad = _gradient_image(size_wh, rbox,
                                   hex_rgb(ov.get("edge1")) or edge, edge2,
                                   float(ov.get("edge_angle") or 0))
            layer.paste(grad, (0, 0), ring)

    # A second colour turns the fill into a gradient. The letters are
    # repainted through their own mask, so the outline keeps its colour.
    fg2 = _lit(hex_rgb(ov.get("fg2")))
    if fg2:
        gm = Image.new("L", size_wh, 0)
        dm = ImageDraw.Draw(gm)
        for x, y, line, ff, pl in pieces:
            _stamp(dm, x, y, line, ff, pl, fill=255)
        bbox = gm.getbbox()
        if bbox:
            grad = _gradient_image(size_wh, bbox,
                                   hex_rgb(ov.get("fg1")) or fg, fg2,
                                   float(ov.get("grad_angle") or 0))
            layer.paste(grad, (0, 0), gm)

    # An INNER GLOW: light coming from the letter's own edge, inwards.
    # There is no offset and no spread to play with - the whole effect is
    # "how far in from the edge am I", and the cheapest honest measure of
    # that is the glyph mask's own blurred inverse: just inside the edge it
    # is bright, and it falls away towards the middle of the stroke. That
    # ramp becomes the alpha, and it is clipped back to the letters so not
    # a pixel of it lands on the artwork.
    igcol = hex_rgb(ov.get("iglow"))
    isize = float(ov.get("iglow_size") if ov.get("iglow_size")
                  not in (None, "") else 5)
    if igcol is None:
        # ...and the OTHER side of the same line. lee: *"add soen iner glow
        # too"*. On a hollow letterform the two halves of one band: the
        # outer lights the paper outside the line, this lights the hole
        # inside it, and the artist's line runs down the middle.
        got = auto_glow(r, lay, fg, edge, ov, key="iglow")
        if got:
            igcol, isize = got[0], float(got[1])
    if igcol and igcol[3]:
        if isize > 0:
            if hole:
                # THE LIGHT COMES OFF THE DRAWN LINE, AND THIS IS THE HALF
                # OF IT THAT GOES INWARD.
                #
                # The pair the block actually has is a ring, and the two
                # glows are the two sides of it: the outer one is cut to
                # the paper outside the letters, this one to the glyph
                # body. Cutting it to the RING instead was the first go,
                # and it was the honest reading of "inside the letterform"
                # - but a rim is four pixels wide, so the effect saturated
                # at once and every number above about three did the same
                # thing. lee: *"inner glow donst acvculy grwo when i
                # increase teh number"*. A knob that does nothing is worse
                # than a knob that does the wrong thing.
                #
                # The ramp is the ring's own blur rather than a blurred
                # inverse: on a hole there is no interior to fall away
                # from, only a line to fall away from, and the reach of
                # that fall is the size.
                ring = _mask(stroke, 0)
                lit = ring.filter(ImageFilter.GaussianBlur(
                    max(0.6, isize * 0.35)))
                body = np.array(_mask(0, 255), np.float32) / 255.0
                a = np.array(lit, np.float32) * body
                # NORMALISED, not lifted by a constant. A blur of a thin
                # line peaks lower the wider the blur, so any fixed lift
                # is tuned to one size: pick it for the small end and the
                # large end is a faint wash, pick it for the large end and
                # everything from about three upwards saturates solid -
                # which is what "it doesn't grow" looked like. Scaling by
                # the ramp's own peak puts full strength at the rim at
                # every size and lets the REACH be what the number buys.
                peak = float(a.max())
                a = np.clip(a * (255.0 / peak if peak > 1 else 1.0),
                            0, 255).astype(np.uint8)
            else:
                im = _mask(0, 255)
                inv = ImageChops.invert(im).filter(
                    ImageFilter.GaussianBlur(isize * 0.6))
                a = (np.array(inv, np.float32)
                     * (np.array(im, np.float32) / 255.0))
                # a blurred edge tops out near half, so it is lifted to
                # reach full strength right at the rim
                a = np.clip(a * 2.1, 0, 255).astype(np.uint8)
            # ...and the same restraint as the outer one: an AUTOMATIC
            # inner glow comes back under full alpha and is faded to it.
            if igcol[3] < 255:
                a = (a.astype(np.uint16) * igcol[3] // 255).astype(np.uint8)
            tint = Image.new("RGBA", size_wh, igcol)
            layer = Image.alpha_composite(
                layer, Image.merge("RGBA", (*tint.split()[:3],
                                            Image.fromarray(a, "L"))))

    return layer


def _fade(layer, op):
    """One layer's TRANSPARENCY, applied once. `op` is 0-100 or absent."""
    if op in (None, ""):
        return layer
    k = max(0.0, min(1.0, float(op) / 100.0))
    if k < 1.0:
        layer.putalpha(layer.split()[3].point(
            lambda v: int(round(v * k))))
    return layer


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
    block's typesetting as a picture - which is what turning a text layer into
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

        m_fg, m_edge, m_stroke = _ink_colours(base, r, lay, needs_halo,
                                              orig=page.image)
        # `style_of`, not the override alone: `inkstyle` measures a glow and
        # a shadow as well as the ink, and reading only the hand corrections
        # would draw the letters in the measured colour with none of the
        # things drawn round them.
        ov = style_of(r)
        fg, edge = colours_for(r, m_fg, m_edge)
        stroke = stroke_for(r, m_stroke)
        fg, edge = _hollow_colours(r, fg, edge)

        spans = _spans_of(r, lay)
        if not spans:
            layer = _ink_layer(pil.size, r, lay, f, ov, fg, edge, stroke)
        else:
            # PART OF THE TEXT IN ITS OWN STYLE, SET RUN BY RUN.
            #
            # There used to be a second way of drawing this, and it was the
            # way a spanned block was drawn unless its ranges changed the
            # metrics: paint the WHOLE line once per style, then cut the
            # copies into vertical bands at the glyph ADVANCES.
            #
            # That cannot work, and lee photographed why. A letter's ink is
            # not inside its advance box - the diagonal of an A overhangs
            # both ways, and a heavy sound-effect face overhangs a long way
            # - so a vertical cut at the advance boundary slices straight
            # through the neighbouring glyph. What you get is a letter with
            # a hard vertical seam down it, half in one colour and half in
            # the other. lee: *"the color sliping to other letter"*, and
            # then the reading that named it exactly: *"it shoud apply to
            # the letter it self and not a box behiod teh letter"*.
            #
            # A band IS a box behind the letter. So there are no bands: the
            # line is set run by run, each run drawn as its own letters at
            # its own accumulated x, and a colour can only ever land on the
            # characters that carry it. Each style still gets one layer of
            # its own, so its glow and its shadow are composited once;
            # nothing is masked, because each layer only ever draws its own
            # characters in the first place.
            layer = Image.new("RGBA", pil.size, (0, 0, 0, 0))
            for st_over, pieces in flow_runs(r, lay, f, ov, spans,
                                             cfg.font_path):
                ov2 = dict(ov)
                ov2.update(st_over)
                fg2, edge2 = colours_for(r, m_fg, m_edge, ov2)
                stroke2 = stroke_for(r, m_stroke, ov2)
                fg2, edge2 = _hollow_colours(r, fg2, edge2, ov2)
                part = _ink_layer(pil.size, r, lay, f, ov2, fg2, edge2,
                                  stroke2, pieces=pieces)
                # TRANSPARENCY, per style: a range may carry its own
                # (lee: every effect *"shoud be able to be doen to
                # xelecetd part of a text box"*), and a span's value
                # REPLACES the block's for its own characters - so each
                # style's layer is faded by its own effective number and
                # the block-level fade below stays off this branch, or a
                # spanned run would be faded twice.
                layer = Image.alpha_composite(
                    layer, _fade(part, ov2.get("opacity")))
        # TRANSPARENCY. It belongs to the whole block - letters, outline,
        # shadow, both glows - so it goes on once, here, after everything that
        # draws and before the balloon clips it. Fading the composited PAGE
        # instead would fade the artwork with it. (A block with spans was
        # faded style by style above.)
        if not spans:
            layer = _fade(layer, ov.get("opacity"))

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
        # ...and a box somebody drew and TURNED. Its block is fitted against the
        # box upright and then turned about the frame's centre, while the mask
        # is the box turned about the BOX's centre - two centres that are close
        # but not the same, so clipping to the mask shaves the ends off lines
        # that fitted perfectly. The box was drawn and angled by hand; where its
        # text goes was decided by the person, not guessed.
        free = free or (getattr(r, "manual", False)
                        and abs(float(getattr(r, "turn", 0.0) or 0.0)) > 0.01)
        # ...and a block set at the minimum size BECAUSE it would not fit its
        # box. Cutting it back to the box here is the spill being undone at the
        # last possible moment, with the words simply missing their first and
        # last letters on the exported page. lee: *"outside text and sfx shoud
        # be able to got outside teh box if the text size is bellow the
        # miimum"*.
        free = free or bool(getattr(lay, "spills", False))
        # The shape the words were FITTED into, which is `place_mask()` unless
        # this block shares a balloon. Two blocks in one balloon are divided by
        # `share_masks`, and it is allowed to divide differently from the
        # detector: a balloon drawn as two lobes goes one lobe to each block
        # whatever the Japanese underneath was arranged like. Clipping the
        # result with `place_mask()` then cut the words back to a shape nothing
        # had fitted them to, and did it silently - a letter standing on the
        # difference simply was not printed, with the fitter's own containment
        # check reporting the block safely inside. lee's page 001 lost the R of
        # REGION that way. Clip with the shape that was measured, or do not
        # claim to be a guarantee.
        area = None if free else ((r.share_mask if r.share_mask is not None
                                   else r.place_mask()) if clip else None)
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
    assumption - it just finds the two populations - and the ink is then named
    by the one thing that is true of ink and false of everything else on the
    page: THERE IS MORE OF IT WHERE THE TEXT IS THAN THERE IS AROUND IT. So the
    same split is applied to the rest of the balloon, outside the text box, and
    whichever class the text box has a bigger share of is the writing.

    That test survives the case a brightness rule cannot: a balloon filled with
    vertical hatching, whose average is nowhere near black, carrying white
    typesetting. Averages call that a light background and typeset it black-on-
    dark; comparing inside against outside sees the hatch give way to white
    exactly where the words are, and calls it white.

    With no surroundings to compare against - a sound effect sitting out on the
    artwork, or a box that already covers the whole balloon - it falls back to
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
    # about - and that is precisely when this used to fall through to the coin
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
    patch. Returns the mean brightness and the share of it that is dark -
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
    # With no mask at all - nothing detected, nothing reloaded - the strip the
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
    say the background decides instead - dark artwork gets white typesetting,
    everything else black. Either way the edge is the opposite colour, which is
    invisible inside a plain white bubble and does the work over tone and art.
    """
    tone = original_tone(orig, region)
    mean, dark_frac = _bg_under(base, region, lay)
    # ...AND THE GLYPHS THEMSELVES GET A VOTE.
    #
    # `original_tone` infers the polarity from the neighbourhood: it splits
    # the box into two populations and asks which one the box has more of than
    # the balloon around it. That needs the balloon to BE a balloon, and on
    # lee's page 019 it is not - the shape attached to id1 is a 258x292
    # rectangle with a ragged bite out of one corner, three of its sides the
    # panel's own edge, most of it hatched artwork. So "outside" is full of
    # dark, the dark class wins outside, and a balloon of plainly black
    # Japanese on white paper comes back as light-on-dark: white letters on
    # white paper, readable only by their rim. lee: *"also can you check what
    # happend heer"*.
    #
    # `inkstyle` measured the same writing at `#020202`. It looks at the glyph
    # pixels rather than at what surrounds them, which is a more direct
    # instrument for this exact question - but not an infallible one: on the
    # BLACK balloon on 009 it also says `#020202`, and there the neighbourhood
    # test is the one that is right.
    #
    # So neither overrules the other. A measured DARK ink withdraws a
    # light-on-dark verdict rather than reversing it, and the background is
    # left to decide - which gets both pages right, because 019's balloon is
    # bright and 009's is black. With nothing measured, nothing changes.
    if tone > 0 and _measured_ink_is_dark(region):
        tone = 0
    # ...and the other way, which was missing for a week. lee sent the TURN
    # effect: `クルッ` drawn in WHITE with a fine black keyline over a dark
    # garment, come back BLACK on white. *"there are some sfx that are
    # invernetd color"*.
    #
    # An effect's box is a rectangle round writing that LEANS across artwork,
    # so it takes in a great deal that is not the writing - a bright sleeve
    # and a lit background as well as the dark cloth the strokes sit on. The
    # neighbourhood test answered for the box, which is mostly light, and the
    # writing in it was white.
    #
    # This one ASSERTS a verdict where the dark test only withdraws one, so it
    # is held to a stricter bar (`INK_LIGHT`, not the midpoint) and the
    # background still overrules it below: white letters on a decidedly LIGHT
    # background would be the same failure with the colours swapped.
    elif tone <= 0 and _measured_ink_is_light(region):
        tone = 1

    # Black typesetting on a dark background cannot be read, whatever the
    # original said. `original_tone` reads the page AS IT ARRIVED, but the
    # words are drawn on the page as it is NOW: the cleaner can leave dark art
    # where a balloon used to be, a frame can be dragged out onto a black
    # panel, and the answer the original gave stops being true. So a decidedly
    # dark background always gets white typesetting with a black edge - the one
    # thing lee has asked for every time this has come up.
    dark_bg = mean < DARK_BG or dark_frac >= 0.55
    # ...UNLESS THE ARTIST ALREADY SOLVED IT, AND WE CAN SEE HOW.
    #
    # lee sent three effects in a row: TURN, FLINCH, and a block of loose
    # narration - *"there are some sfx that are invernetd color"*, *"fleinck
    # to and a few more and teh freefloat text too"*. Two of them are this
    # case. `ビクッ` is drawn in BLACK with a fine white keyline over a grey
    # cloak, and the narration the same way over dark screentone; both came
    # back WHITE on black, which is the page saying the opposite of what the
    # artist said.
    #
    # The rule above is right about balloons and was overreaching on artwork.
    # Black letters on dark art are unreadable WITH NOTHING ROUND THEM - and
    # on artwork there is always something round them, because `needs_halo` is
    # what puts it there. That is exactly how the original is drawn: dark
    # strokes, light keyline, on dark cloth. Copying it is not a risk, it is
    # the answer the page already contains.
    #
    # Inside a BALLOON there is no halo - the edge is a hairline that does not
    # hold anything off anything - so the dark-background rule keeps the last
    # word there, which is what page 009's solid black balloon needs.
    if dark_bg and needs_halo and _measured_ink_is_dark(region):
        dark_bg = False

    if tone > 0 or dark_bg:
        fg, edge = (255, 255, 255, 255), (0, 0, 0, 255)
        width = max(OUTLINE_ON_ART, rim_for(region, lay.font_size))
    else:
        fg, edge = (0, 0, 0, 255), (255, 255, 255, 255)
        width = max(OUTLINE_ON_ART, rim_for(region, lay.font_size)) if needs_halo \
            else max(OUTLINE_IN_BUBBLE, lay.font_size // 14)
    return fg, edge, _measured_width(region, lay, width)


# How far the automatic halo reaches, as a fraction of the type size, and the
# floor under it.
#
# SMALL. lee, having looked at the first version: *"it shou be small"*. It went
# out at 0.07 of the type - eleven pixels on a 160pt effect - which is a halo
# you look at rather than one that does its job. The job is to hold a LINE off
# the artwork it is drawn over, and a line is a few pixels wide, so the light
# either side of it is a few pixels too. At 0.035 a 160pt sound gets six, a
# 40pt one gets the floor, and neither of them is a cloud.
#
# A ratio all the way up, unlike a rim: a rim is a pen and a pen has a width,
# but how much room a word needs round it is proportional to the word.
GLOW_EM = 0.035
GLOW_MIN = 3
# How solid an automatic halo is. See `auto_halo`.
AUTO_ALPHA = 102


def auto_halo(fg, edge, font_size):
    """The light a HOLLOW letterform gets on both sides of its line.

    lee asked for this on a white COLLAPSE keylined in black over grey
    hatching - *"thses type of sfx shodu also hVE OUTER glow of teh oposite
    color"* - and then, when the first version put one on every sound effect on
    the page: *"the outerglow asked for was for teh traparent text only and it
    shou be small and add soen iner glow too"*.

    So: **transparent text only**, which is what the first version got wrong.
    A letter with a fill has a fill to hold it off the page. A letter that is
    only a line has a few pixels of ink and the artwork on both sides of them,
    and that is the block that cannot be read on a busy panel.

    **Both sides of the line**, which is what an inner glow is for here. On a
    solid letter "inner" means light falling away from the edge into the body;
    on a hollow one there is no body, only a line, so the outer glow lights the
    paper outside it and the inner glow lights the hole inside it. Together
    they are a soft band down the middle of which the artist's line runs.
    `render_page` already draws both that way - it has a `hole` branch for each
    - so this only has to say the colour and the size.

    **The opposite colour, and the opposite of the RIM.** On a hollow block
    `_hollow_colours` has already moved the ink onto the edge: the rim IS the
    letter. A halo in the rim's own colour is nothing at all, so this takes the
    contrasting one - white behind a dark line, black behind a light one, which
    is the same pair `_ink_colours` picks by the same rule.

    Returns `(rgba, px)`, or None when the block is not a hollow one. `fg` and
    `edge` may be tuples or the CSS strings a stored layout carries.
    """
    fill = fg if isinstance(fg, (tuple, list)) else any_rgb(fg)
    rim = edge if isinstance(edge, (tuple, list)) else any_rgb(edge)
    # "Transparent text", in the one form the app has for it: a fill with no
    # alpha. Asked of the DRAWN colour rather than of the `hollow` flag, so a
    # block somebody emptied by hand counts as much as one `inkstyle` read that
    # way - both are letters with nothing inside them, which is the thing this
    # is about.
    if not fill or len(fill) < 4 or fill[3] != 0:
        return None
    if not rim:
        return None
    try:
        px = max(GLOW_MIN, int(round(float(font_size) * GLOW_EM)))
    except (TypeError, ValueError):
        px = GLOW_MIN
    # UNDER FULL ALPHA, and that is not a detail. A halo nobody asked for has
    # to be a light and not a sticker: at full strength the exporter's own
    # doubling made an opaque band six pixels wide round every letter, which on
    # a white page merged between the letters into a slab. At 40% it is what
    # lee asked for - *"it shou be small"* - which is as much about how much of
    # it there is as about how far it reaches.
    lit = (255, 255, 255) if sum(rim[:3]) < 384 else (0, 0, 0)
    return lit + (AUTO_ALPHA,), px


def auto_glow_bits(fg, edge, font_size, ov, key="glow"):
    """`auto_halo`, with the one question a caller always has to ask first:
    has somebody already answered this?

    A glow they chose wins, and so does a glow they turned OFF - an eight-digit
    hex with a zero alpha is how the × writes *no glow*, and that is a choice
    like any other. A SIZE they set wins too, because they set it looking at
    this block.

    `key` is `glow` or `iglow`: the same halo, asked for either side of the
    line, so that the two can be turned off one at a time.
    """
    ov = ov or {}
    if hex_rgb(ov.get(key)) is not None:
        return None                       # chosen, or deliberately turned off
    got = auto_halo(fg, edge, font_size)
    if not got:
        return None
    lit, px = got
    want = ov.get(key + "_size")
    if want not in (None, ""):
        try:
            px = max(0, int(round(float(want))))
        except (TypeError, ValueError):
            pass
    return (lit, px) if px > 0 else None


def auto_glow(region, lay, fg, edge, override=None, key="glow"):
    """The same, for a caller holding a region and its layout."""
    return auto_glow_bits(fg, edge, lay.font_size,
                          style_of(region, override), key)


def rim_for(region, size) -> int:
    """How thick an outline is when nobody has measured or chosen one.

    `size // 7` at the small end, and a crawl past `RIM_KNEE` - the constants
    carry the measurement off lee's chapter and the reason the knee is where
    it is.

    **Every sound effect, the big ones included.** It was every sound effect
    EXCEPT the big ones - lee: *"that shoud only apply for the other sfx"*,
    *"ot the big ones"* - on the reasoning that where nothing was measured, an
    impact effect is the one place a heavy rim is the drama rather than a
    mistake. He looked at the result and asked for the exemption back:
    *"the big sfx shoud also use rim now"*.

    He is right, and the reasoning was thinner than it sounded. A big sound is
    where `size // 7` is at its WORST: it is a ratio, so the block with the
    largest type gets the heaviest keyline, and 144pt asks for twenty pixels
    where his chapter's artist drew four. "The drama" was a defence of the one
    case the measurement most flatly contradicts.

    **Not for anything that is not a sound.** Dialogue never comes through
    here at all - a block inside a balloon takes the hairline branch above -
    and free text on the artwork keeps the old rule, because nobody has
    measured that.

    A block that WAS measured keeps its measured rim regardless of any of
    this: `_measured_width` is applied after, and this is the answer for pages
    nobody has read.

    The family is asked, not the sub-type list: with no registry loaded an
    unknown sub-type reads as a bubble and keeps the old rule, which is the
    safe direction - it changes nothing rather than thinning something nobody
    could check.
    """
    size = int(size)
    kind = getattr(region, "kind", "") or ""
    if _kinds.family_of(kind) != "sfx":
        return size // 7
    if size <= RIM_KNEE:
        return size // 7
    return int(round(RIM_KNEE / 7.0 + (size - RIM_KNEE) / float(RIM_SLOW)))


def _measured_ink_is_dark(region) -> bool:
    """Did `inkstyle` read the original writing as DARK ink?

    Off `layout_measured` and not off `style_of`, deliberately: this is not
    the block's colour and is never drawn. It is the one fact the measurement
    knows that the neighbourhood test is guessing at, and a bubble is entitled
    to it even though a bubble may not take a measured colour - lee's rule is
    about what gets PRINTED, and nothing here gets printed.

    False when nothing was measured, which leaves every page that has not been
    through `measure_page` exactly as it was.
    """
    ink = _measured_ink(region)
    return ink is not None and sum(ink[:3]) < 3 * INK_MID


def _measured_ink(region):
    return hex_rgb((getattr(region, "layout_measured", None) or {}).get("fg"))


# How light a measured ink has to be before it is taken for WHITE writing.
#
# Not the mirror of `INK_MID`, and deliberately: a mid-grey ink says nothing,
# and the case this exists for is unambiguous - Japanese drawn in white over
# dark artwork, which `inkstyle` reads at 230 and up. The dark test can afford
# the loose half of the range because getting it wrong there withdraws a
# verdict; this one ASSERTS one, so it is only allowed to speak when it is
# certain.
INK_MID = 128
INK_LIGHT = 200


def _measured_ink_is_light(region) -> bool:
    """Did `inkstyle` read the original writing as WHITE ink?

    The mirror of the test above, and it was missing. lee sent the TURN
    effect: `クルッ` drawn in WHITE with a fine black keyline over a dark
    garment, coming back as BLACK letters with a white keyline - inverted.
    *"can you look into the turn sfx thare are some sfx that are invernetd
    color"*.

    Nothing was wrong with the arithmetic. An effect's box is a rectangle
    round writing that leans across artwork, so it catches a great deal of
    what is NOT the writing - here a bright sleeve and a lit background as
    well as the dark cloth the strokes actually sit on. The neighbourhood test
    saw a box that is mostly light and answered dark-on-light, which is what
    the box is and not what the writing was.

    The glyph pixels are not guessing at that: they were measured, and they
    are white.
    """
    ink = _measured_ink(region)
    return ink is not None and sum(ink[:3]) >= 3 * INK_LIGHT


def _hollow_colours(region, fg, edge, override=None):
    """Writing drawn as an outline has NOTHING inside it, and the LINE is the ink.

    Two swaps, and the second one is the half I shipped without and had to go
    back for.

    **The inside.** Filling a hollow letterform with paper turns it into an
    opaque white shape: のびー lets the bath and the tiles show through its
    counters, and STRETCH set the same way in solid white blanked the panel it
    was drawn on. So the fill is nothing at all and the artwork shows through.

    **The line.** `edge` is a HALO - the colour chosen to hold the letters off
    whatever is behind them, which on light artwork is white. Draw a hollow
    letter with a transparent middle and a white rim and there is nothing on
    the page at all; that is what the first go looked like. The rim of a
    hollow letter is not a halo, it IS the letter, so it takes the colour the
    letters were going to be.

    THE COLOUR IS NOT AN EXCEPTION, and the first version of this made it one
    - `if ov.get("fg"): return` - which would have meant the whole thing never
    fired at all, because `inkstyle` writes a colour for every region it can
    read. The measured ink IS the colour wanted here: the ink is what the line
    is drawn in.

    (That paragraph used to end *"and there is nothing in the record to tell
    the two apart"*, about the measurement and a hand choice sharing
    `layout_override`. There is now: they are separate fields, and `style_of`
    ranks them. What that ambiguity cost is written up on
    `models.TextRegion.layout_measured`.)

    THE OUTLINE IS THE EXCEPTION, though, and only because it is hand-set.
    The paragraph above is about the AUTOMATIC edge - a halo, chosen by
    `_ink_colours` against the artwork, which knows nothing about a letterform
    that is only a line. A person choosing a colour for the outline of a block
    whose outline is the whole of it has said the one thing there is to say
    about it. lee, with a hollow SPLAAASH and `#ff0000` in the outline well:
    *"teh outline color donet do anything even thoug teh outline is what is
    left"*.

    The FILL is not an exception, and deliberately, though it would be the
    obvious way to ask for a filled letterform. `saveTypesetting` writes the
    fill well's value into `layout_override` on any save, and until the well
    learned to say "none" that value was the measured ink - so a chapter
    worked on before today has the ink sitting in the override on every hollow
    block it has, and reading that as a choice would turn every one of them
    solid. Turning the finding off wants a control of its own.
    """
    ov = style_of(region, override)
    if not ov.get("hollow"):
        return fg, edge
    hand = hand_style(region, override)
    # AN OUTLINE SET BY HAND WINS, for on a block like this the outline is all
    # there is.
    #
    # The rim takes the INK's colour because an automatic `edge` is a halo -
    # a colour chosen to hold the letters off the page - and a hollow letter
    # drawn in a halo colour is nothing on the page at all. That reasoning is
    # about the AUTOMATIC edge. A hand choice is not a halo; it is the answer.
    # lee, with a hollow SPLAAASH and #ff0000 in the outline well: *"teh
    # outline color donet do anything even thoug teh outline is what is left"*.
    rim = hex_rgb(hand.get("edge"))
    if rim is None or rim[3] == 0:
        rim = tuple(fg[:3])
    return tuple(fg[:3]) + (0,), tuple(rim[:3]) + (255,)


def _measured_width(region, lay, width: int, override=None) -> int:
    """The outline width the ORIGINAL writing had, where it was measured.

    Everything above works the width out as a fraction of the point
    size, which is a rule of thumb about legibility and knows
    nothing about the page. On writing drawn as a hollow outline
    that is not a halo at all - the rim IS the letterform - and the
    rule of thumb gets it wrong in the direction that shows. lee,
    on page 006: *"for the stratch sfx it not even close"*. のびー
    has a two-pixel rim; `font_size // 7` put a fourteen-pixel one
    round STRETCH.

    IN PIXELS, not scaled to the point size. A pen has a width: the
    artist drew the big effect and the small one with the same nib,
    and the line it leaves is the same line whatever size the
    letters are. Scaling it gave STRETCH a 1px rim beside のびー's
    2 - proportionally identical and visibly half as thick on the
    same sheet of paper. lee: *"if you could get it to match the
    ouline and bordee size it would be perfect"*.
    """
    ov = style_of(region, override)
    if not ov.get("hollow"):
        return int(width)
    try:
        rim = int(ov.get("rim") or 0)
    except (TypeError, ValueError):
        return int(width)
    if rim <= 0:
        return int(width)
    return max(1, min(30, rim))


# --------------------------------------------------------- the box sheet
#
# The page with the boxes drawn onto it, as a file. lee: "add a button n in the
# export that allow me to export the picture with the boxes".
#
# It is a copy of what the editor already draws on screen, and the point of it
# is that it looks the SAME - a sheet you can hand to somebody, print, or put
# beside the editor while you work through a chapter is worth nothing if its
# colours mean something different from the ones on screen. So these four
# colours are the four in `static/js/frames.js`, and a test parses that file
# and fails if the two ever drift apart.
# Three families, and the shades a sub-type of each may be - see kinds.py.
# There used to be six unrelated colours here for six flat types.
KIND_COLOURS = dict(_kinds.FAMILY_COLOUR)
# One colour for every linked pair, not one per group.
# lee: *"make the lunks just one color so all the link shoud be one color"*.
# Six link colours meant six more things on the page competing with the six
# text-type colours, and which link was which was never the question - the
# question is only ever "are these two joined".
LINK_COLOUR = "#2a63d8"
# The three alphas the stylesheet uses: `.box{background:kc+'22'}` is 0x22/255,
# `.gbox` is 6%, and `.bhint`'s border is kc+'88'.
BOX_FILL = 0x22 / 255.0
GROUP_FILL = 0.06
HINT_INK = 0x88 / 255.0
HINT_MIN = 1.25          # a balloon is only worth drawing when it is this much
                         # bigger than the writing - same test as frames.js


def _bgr(hexstr: str) -> tuple[int, int, int]:
    rgb = hex_rgb(hexstr) or (136, 136, 136, 255)
    return (rgb[2], rgb[1], rgb[0])


def kind_colour(kind: str, custom=()) -> str:
    """The colour of a text type: one definition, in kinds.py."""
    return _kinds.kind_colour(kind, custom)


def link_colour(group: int = 1) -> str:
    return LINK_COLOUR


def contrast_text(hexstr: str) -> tuple[int, int, int]:
    """Black or white on a given colour, whichever reads - frames.js's sum."""
    r, g, b, _ = hex_rgb(hexstr) or (136, 136, 136, 255)
    return (22, 22, 22) if (0.299 * r + 0.587 * g + 0.114 * b) > 150 \
        else (255, 255, 255)


class _Ink:
    """One transparent sheet to draw all the furniture on, composited once.

    Every piece of this has its own opacity - a 13% fill, a half-lit dashed
    balloon, a solid border - and blending each one against the page as it is
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

    `records` are the stored region dicts - the same ones the browser is sent -
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

    # Two sections of one balloon draw their own boxes dashed and quiet - the
    # balloon is the thing that is one, and the sections are the things you
    # pick.
    #
    # A solid frame used to be drawn round the pair as well. lee, finding one
    # on a burst holding two speeches: *"there a big box with no label or
    # anything"*, then *"hide teh big box afterware it dosnt need to be
    # visibel"*. Gone from the editor and gone from here in the same move -
    # the sheet shows what the screen shows, which is the rule that took the
    # balloon hint out of both. `GROUP_FILL` stays: the sheet's other
    # opacities are checked against it.
    groups: dict[int, list] = {}
    for r in recs:
        g = int(r.get("box_group") or 0)
        if g > 0:
            groups.setdefault(g, []).append(r)
    groups = {g: m for g, m in groups.items() if len(m) > 1}
    sectioned = {id(r) for m in groups.values() for r in m}

    # The balloon used to be drawn here too, faint and dashed behind the
    # writing. It went with the editor's `.bhint` on 2026-07-30 - lee: *"there a
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
            # SECTIONS OF ONE BALLOON GET THE LINE TOO. They were the one case
            # that did not - "the group frame already says they are one thing"
            # - and that frame is gone, twice asked for: lee, *"hide teh big
            # box afterware it dosnt need to be visibel"*. Nothing took over
            # saying it, and on screen `.box.section` forces the dashes back
            # on over `.box.linked`'s solid border, so a linked pair of
            # sections was drawn exactly like two unrelated boxes. lee: *"the
            # link is not showing"*.
            #
            # Changed here as well as in `frames.js` and not instead of it:
            # the sheet shows what the screen shows.
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
