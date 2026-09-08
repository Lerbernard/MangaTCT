"""The marks that go IN a line: a heart, a star, a sweat drop, an anger vein.

lee, with a crop of 「これから本番♥」: *"i want teh read text to be able to read
stuff like haearts and other thiungs that text can usualy have ... i wan a big
librey of icons that can be put there"*.

## Why they are drawn here and not typed

Because the typesetting faces cannot draw them. Measured over the sixteen faces
this app ships, for eighteen marks manga actually uses:

    ComicNeue (the speech face)     none at all
    Bangers, Chewy, Luckiest Guy    none
    Jua                             heart, hollow heart, star, hollow star
    Patrick Hand                    heart

So `♥` in a line of Comic Neue is an empty box on the page - which is exactly
why three prompts used to strip marks out, and why the rule that did it was
right at the time. See `typeset.mark_glyph` for the substitution and
`translate.build_ocr_system` for the rule that changed.

A mark is a SHAPE here rather than a glyph borrowed from a symbol font. Both
were built and looked at side by side: a font's heart is angular with a long
tail and reads as a playing card, and these are round with a short point, which
is the heart manga draws and the one in lee's own crop.

## The shapes

Each mark is a list of closed paths in a 100x100 box. A path is a list of
segments: ("M",x,y), ("C",x1,y1,x2,y2,x,y), ("L",x,y). A path wrapped as
("hole", path) is drawn LAST and erases - the eye of a skull, the middle of a
flower - because PIL fills polygons and cannot leave a hole any other way.
Rendered by flattening the beziers and filling the polygons at 4x, then
downsampling - which is what gives a clean edge without needing a real
rasteriser.

EVERY character the picker offers is drawn here since the 2026-08-31 redo.
There used to be a second source - "whatever font on this machine has it" -
and on lee's own machine half the picker came out as tofu squares, because
Windows fonts cover ♫ and ☺ (old code-page leftovers) and not ♬ or ☹. A
library where half the buttons are boxes is not a library. The donor lookup
in `typeset` stays as a safety net for a character a line carries that this
module has never heard of, but nothing the picker OFFERS depends on it.
"""
import math

from PIL import Image, ImageDraw

SS = 4          # supersample


def _bez(p0, p1, p2, p3, n=24):
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u*u*u*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0],
                    u*u*u*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1]))
    return out


def _flatten(path):
    pts, cur = [], (0.0, 0.0)
    for seg in path:
        k = seg[0]
        if k == "M":
            cur = (seg[1], seg[2]); pts.append(cur)
        elif k == "L":
            cur = (seg[1], seg[2]); pts.append(cur)
        elif k == "C":
            nxt = (seg[5], seg[6])
            pts += _bez(cur, (seg[1], seg[2]), (seg[3], seg[4]), nxt)
            cur = nxt
    return pts


def _star(n, ro, ri, rot=-90.0):
    path = []
    for i in range(n * 2):
        r = ro if i % 2 == 0 else ri
        a = math.radians(rot + i * 180.0 / n)
        x, y = 50 + r * math.cos(a), 50 + r * math.sin(a)
        path.append(("M" if i == 0 else "L", x, y))
    return path


# --- the small geometry the new shapes are put together from ---------------

def _ellipse(cx, cy, rx, ry):
    kx, ky = rx * 0.5523, ry * 0.5523
    return [("M", cx, cy - ry),
            ("C", cx + kx, cy - ry, cx + rx, cy - ky, cx + rx, cy),
            ("C", cx + rx, cy + ky, cx + kx, cy + ry, cx, cy + ry),
            ("C", cx - kx, cy + ry, cx - rx, cy + ky, cx - rx, cy),
            ("C", cx - rx, cy - ky, cx - kx, cy - ry, cx, cy - ry)]


def _circle(cx, cy, r):
    return _ellipse(cx, cy, r, r)


def _arc(cx, cy, rx, ry, a0, a1, n=28):
    """Points along an ellipse arc, degrees, y down (90 is DOWN)."""
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
            for i in range(n + 1)]


def _band(pts, w):
    """A stroke as a SHAPE: the polyline fattened to width `w`.

    How a question hook, a smiling mouth and a dizzy spiral get drawn filled -
    offsetting every point along its normal both ways and closing the ring.
    The alternative, drawing them with a thick line at raster time, cannot be
    a `hole` and cannot be hollowed, so it would be a second kind of path.
    """
    h = w / 2.0
    left, right = [], []
    n = len(pts)
    for i, (x, y) in enumerate(pts):
        x0, y0 = pts[max(0, i - 1)]
        x1, y1 = pts[min(n - 1, i + 1)]
        dx, dy = x1 - x0, y1 - y0
        seg = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / seg, dx / seg
        left.append((x + nx * h, y + ny * h))
        right.append((x - nx * h, y - ny * h))
    ring = left + right[::-1]
    return [("M", ring[0][0], ring[0][1])] + \
        [("L", x, y) for x, y in ring[1:]]


def _rot(paths, deg, cx=50.0, cy=50.0):
    """The same paths turned about a centre - what makes five petals of one."""
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for p in paths:
        q = []
        for seg in p:
            vals = list(seg[1:])
            for i in range(0, len(vals), 2):
                x, y = vals[i] - cx, vals[i + 1] - cy
                vals[i] = cx + x * ca - y * sa
                vals[i + 1] = cy + x * sa + y * ca
            q.append((seg[0], *vals))
        out.append(q)
    return out


def _zed(cx, cy, s):
    """One Z, half-size `s` - three of them at falling sizes are 💤."""
    t, dt = s * 0.5, s * 0.8
    x0, y0, x1, y1 = cx - s, cy - s, cx + s, cy + s
    return [("M", x0, y0), ("L", x1, y0), ("L", x1, y0 + t),
            ("L", x0 + dt, y1 - t), ("L", x1, y1 - t), ("L", x1, y1),
            ("L", x0, y1), ("L", x0, y1 - t), ("L", x1 - dt, y0 + t),
            ("L", x0, y0 + t)]


HEART = [[("M", 50, 90),
          ("C", 18, 66, 5, 50, 5, 33),
          ("C", 5, 17, 17, 6, 30, 6),
          ("C", 40, 6, 47, 12, 50, 21),
          ("C", 53, 12, 60, 6, 70, 6),
          ("C", 83, 6, 95, 17, 95, 33),
          ("C", 95, 50, 82, 66, 50, 90)]]


SPARKLE = [[("M", 50, 2),
            ("C", 55, 32, 68, 45, 98, 50),
            ("C", 68, 55, 55, 68, 50, 98),
            ("C", 45, 68, 32, 55, 2, 50),
            ("C", 32, 45, 45, 32, 50, 2)]]

DROP = [[("M", 50, 4),
         ("C", 58, 22, 86, 50, 86, 67),
         ("C", 86, 83, 70, 95, 50, 95),
         ("C", 30, 95, 14, 83, 14, 67),
         ("C", 14, 50, 42, 22, 50, 4)]]

STAR5 = [_star(5, 48, 20)]

NOTE = [[("M", 74, 8),
         ("C", 74, 8, 74, 56, 74, 62),
         ("C", 74, 62, 62, 56, 50, 62),
         ("C", 36, 69, 30, 82, 36, 90),
         ("C", 42, 98, 58, 96, 66, 86),
         ("C", 72, 79, 72, 72, 72, 62),
         ("L", 72, 26),
         ("C", 80, 30, 90, 36, 92, 46),
         ("C", 96, 34, 90, 18, 74, 8)]]

# The anger vein, the mark drawn on a forehead: four angle brackets pointing
# in at a centre. Each lobe is a chevron - outer corner, in to the middle,
# back out - so the whole reads as a cross of popped veins.
def _lobe(cx, cy, dx, dy, long=34, thick=12):
    """One chevron, its point at (cx,cy), arms running out along (dx,dy)."""
    return [("M", cx, cy),
            ("L", cx + dx * long, cy),
            ("L", cx + dx * long, cy + dy * thick),
            ("L", cx + dx * thick, cy + dy * thick),
            ("L", cx + dx * thick, cy + dy * long),
            ("L", cx, cy + dy * long)]


VEIN = [_lobe(42, 42, -1, -1, 40, 12), _lobe(58, 42, 1, -1, 40, 12),
        _lobe(42, 58, -1, 1, 40, 12), _lobe(58, 58, 1, 1, 40, 12)]

EXCL = [[("M", 38, 6), ("L", 62, 6), ("L", 57, 60), ("L", 43, 60)],
        [("M", 50, 70), ("C", 58, 70, 63, 76, 63, 83),
         ("C", 63, 90, 58, 96, 50, 96),
         ("C", 42, 96, 37, 90, 37, 83),
         ("C", 37, 76, 42, 70, 50, 70)]]

# A puff of sweat / relief - three teardrops in a fan.
SWEAT = [[("M", 26, 12), ("C", 30, 24, 44, 38, 44, 50),
          ("C", 44, 61, 36, 68, 26, 68),
          ("C", 16, 68, 8, 61, 8, 50),
          ("C", 8, 38, 22, 24, 26, 12)],
         [("M", 74, 26), ("C", 77, 36, 88, 47, 88, 57),
          ("C", 88, 66, 82, 72, 74, 72),
          ("C", 66, 72, 60, 66, 60, 57),
          ("C", 60, 47, 71, 36, 74, 26)]]

def _scaled(paths, k, dx=0.0, dy=0.0):
    """One shape shrunk about its own centre and moved."""
    out = []
    for p in paths:
        q = []
        for seg in p:
            vals = list(seg[1:])
            for i in range(0, len(vals), 2):
                vals[i] = 50 + (vals[i] - 50) * k + dx
                vals[i + 1] = 50 + (vals[i + 1] - 50) * k + dy
            q.append((seg[0], *vals))
        out.append(q)
    return out


# ✨ is three of them - one large, two small - and that is the whole difference
# between it and ✦.
SPARKLES = (_scaled(SPARKLE, 0.62, -12, 6)
            + _scaled(SPARKLE, 0.34, 20, -22)
            + _scaled(SPARKLE, 0.26, 26, 26))

# --- the 2026-08-31 additions: the rest of what manga actually writes -------

# ❣ - a heart where an exclamation mark keeps its dot.
HEARTEXCL = _scaled(HEART, 0.62, 0, -20) + [_circle(50, 84, 11)]

# 💕 - two hearts, the smaller tucked against the larger.
HEARTS2 = _scaled(HEART, 0.62, -15, -12) + _scaled(HEART, 0.46, 20, 18)

# ⚡ - the shock bolt.
BOLT = [[("M", 60, 2), ("L", 20, 58), ("L", 42, 58), ("L", 36, 98),
         ("L", 80, 40), ("L", 55, 40)]]

# 💤 - three Zs at falling sizes, climbing away.
ZZZ = [_zed(20, 72, 22), _zed(58, 42, 15), _zed(85, 14, 10)]

# 💫 - a star with the comet swoosh under it.
DIZZY = (_scaled(STAR5, 0.60, 4, -16)
         + [_band(_arc(50, 54, 42, 26, -25, 205, n=40), 8)])

# 🌀 - the dizzy spiral. Starts a half-turn out so the band cannot cross
# itself, which PIL's fill would punch a hole through.
SWIRL = [_band([(50 + (2 + 2.75 * (2.0 + i * 0.15))
                 * math.cos(2.0 + i * 0.15),
                 50 + (2 + 2.75 * (2.0 + i * 0.15))
                 * math.sin(2.0 + i * 0.15))
                for i in range(int((15.7 - 2.0) / 0.15) + 1)], 7.5)]

# ☺ / ☹ - a face is a filled circle and three holes.
_EYES = [("hole", _circle(34, 37, 6.5)), ("hole", _circle(66, 37, 6.5))]
SMILE = [_circle(50, 50, 46)] + _EYES + \
    [("hole", _band(_arc(50, 46, 26, 25, 35, 145, n=24), 7.5))]
FROWN = [_circle(50, 50, 46)] + _EYES + \
    [("hole", _band(_arc(50, 90, 25, 18, 215, 325, n=24), 7.5))]

# ☠ - crossbones behind, head and jaw over them, eyes and nose out of those.
SKULL = [_band([(8, 68), (92, 92)], 9), _band([(92, 68), (8, 92)], 9),
         _ellipse(50, 38, 33, 34),
         [("M", 34, 58), ("L", 66, 58), ("L", 66, 86), ("L", 34, 86)],
         ("hole", _circle(37, 36, 8.5)), ("hole", _circle(63, 36, 8.5)),
         ("hole", [("M", 50, 48), ("L", 56, 60), ("L", 44, 60)])]

# ✿ - five petals about a punched-out middle; ❀ is the same flower hollow.
FLOWER = [q for k in range(5)
          for q in _rot([_ellipse(50, 24, 14, 20)], k * 72.0)] + \
    [("hole", _circle(50, 50, 7))]

# ♩ ♫ ♬ - the notes ♪ was missing. Real beamed pairs, not the single-note
# shape three times over (which is what mapping them to ♪ used to draw, and
# why they were left to a donor font that half of lee's fonts did not have).
QNOTE = [_ellipse(44, 78, 17, 12),
         [("M", 58, 10), ("L", 65, 10), ("L", 65, 80), ("L", 58, 80)]]

_BEAM1 = [("M", 30, 10), ("L", 88, 4), ("L", 88, 18), ("L", 30, 24)]
_BEAM2 = [("M", 30, 30), ("L", 88, 24), ("L", 88, 38), ("L", 30, 44)]
_STEMS = [[("M", 30, 17), ("L", 36, 17), ("L", 36, 84), ("L", 30, 84)],
          [("M", 82, 10), ("L", 88, 10), ("L", 88, 78), ("L", 82, 78)]]
_HEADS = [_ellipse(24, 84, 14, 10), _ellipse(76, 78, 14, 10)]
NOTES2 = [_BEAM1] + _STEMS + _HEADS
NOTES16 = [_BEAM1, _BEAM2] + _STEMS + _HEADS

# ❓ - the hook fattened to a band, and the dot the ❗ already has.
QUES = [_band(_bez((28, 32), (26, 2), (78, 4), (74, 34), n=20)
              + _bez((74, 34), (72, 52), (56, 50), (53, 64), n=14)[1:], 13),
        _circle(50, 88, 9.5)]

# ‼ and ⁉ - what a balloon actually shouts.
EXCL2 = _scaled(EXCL, 0.92, -19, 0) + _scaled(EXCL, 0.92, 19, 0)
EXCLQ = _scaled(EXCL, 0.92, -24, 0) + _scaled(QUES, 0.92, 19, 0)

MARKS = {"heart": HEART, "sparkle": SPARKLE, "sparkles": SPARKLES,
         "drop": DROP, "star": STAR5, "note": NOTE, "vein": VEIN,
         "excl": EXCL, "sweat": SWEAT,
         "heartexcl": HEARTEXCL, "hearts2": HEARTS2, "bolt": BOLT,
         "zzz": ZZZ, "dizzy": DIZZY, "swirl": SWIRL, "smile": SMILE,
         "frown": FROWN, "skull": SKULL, "flower": FLOWER, "qnote": QNOTE,
         "notes2": NOTES2, "notes16": NOTES16, "ques": QUES,
         "excl2": EXCL2, "exclq": EXCLQ}

# Which character stands for which shape, and how it is drawn.
#
# The CHARACTER is what travels: it is what the reader transcribes, what the
# translator carries across, what sits in `dst_text` and what a person types.
# Nothing anywhere else in the app knows these are drawn rather than typeset -
# a line holding one is a string like any other, and the substitution happens
# at the last moment, in `typeset.mark_glyph`.
#
# Real Unicode characters and not private-use codepoints, deliberately. A
# chapter exported to somebody else's editor, pasted into a document, or opened
# by a version of this app that has never heard of marks still SAYS what the
# balloon says. A private codepoint would be a box everywhere but here.
#
# `hollow` is the outline weight as a fraction of the mark's height: ♡ is ♥
# drawn as a line rather than filled, which is the same shape and a different
# character.
GLYPHS = {
    "♥": ("heart", 0.0),        # ♥
    "♡": ("heart", 0.13),       # ♡
    "❤": ("heart", 0.0),        # ❤  same shape; kept so a line carrying the
                                #    emoji-styled heart still draws, but NOT
                                #    offered in the picker - two buttons that
                                #    put the same picture on the page are one
                                #    button and a question.
    "★": ("star", 0.0),         # ★
    "☆": ("star", 0.13),        # ☆
    "✦": ("sparkle", 0.0),      # ✦
    "✧": ("sparkle", 0.13),     # ✧
    "✨": ("sparkles", 0.0),     # ✨  three of them, not one
    "♪": ("note", 0.0),         # ♪
    "♫": ("notes2", 0.0),       # ♫  a real beamed pair now - mapping it to
    "♬": ("notes16", 0.0),      # ♬  the single note drew ♪ twice over
    "♩": ("qnote", 0.0),        # ♩
    "❣": ("heartexcl", 0.0),    # ❣
    "\U0001f495": ("hearts2", 0.0),  # 💕
    "\U0001f4a6": ("sweat", 0.0),    # 💦
    "\U0001f4a2": ("vein", 0.0),     # 💢
    "\U0001f4a7": ("drop", 0.0),     # 💧
    "\U0001f4a4": ("zzz", 0.0),      # 💤
    "\U0001f4ab": ("dizzy", 0.0),    # 💫
    "\U0001f300": ("swirl", 0.0),    # 🌀
    "⚡": ("bolt", 0.0),         # ⚡
    "☺": ("smile", 0.0),        # ☺
    "☹": ("frown", 0.0),        # ☹
    "☠": ("skull", 0.0),        # ☠
    "✿": ("flower", 0.0),       # ✿
    "❀": ("flower", 0.10),      # ❀  the same flower drawn as a line
    "❗": ("excl", 0.0),         # ❗
    "❕": ("excl", 0.10),        # ❕
    "‼": ("excl2", 0.0),        # ‼
    "⁉": ("exclq", 0.0),        # ⁉
    "❓": ("ques", 0.0),         # ❓
    "❔": ("ques", 0.10),        # ❔
}


def for_char(ch: str):
    """(shape name, hollow) for a character this module can draw, or None."""
    return GLYPHS.get(ch)


# The picker, in the order it is shown, in groups. (character, what it is).
#
# ONE LIST, and the app reads it from here. The browser is served the
# characters and asks the server for a picture of each - it cannot draw them,
# and a second set of shapes in JavaScript is the same mistake as a second copy
# of `DEFAULT_FONTS` there: two drawings that agree until one is edited.
#
# Every character here has a shape above - lee's screenshot of the picker
# showed twelve tofu squares, one for each character that was left to "a font
# on this machine", and the redo was his ask: *"redo thsi who qhole yhing and
# add a buch more common manag mahwa icons"*. ✩, ✪ and ♭ went in the same
# breath: ✩ drew the same star as ☆, ✪ turned up in nobody's balloons, and a
# flat sign is sheet music, not dialogue. They are in the list because they
# turn up in dialogue; a symbol that only ever appears as artwork is not,
# because *"the app shou only worry about symobys in the text not any other
# symobs"*.
PICKER = (
    ("Hearts", (("♥", "heart"), ("♡", "hollow heart"),
                ("\U0001f495", "two hearts"), ("❣", "heart exclamation"))),
    ("Stars & sparkles", (("★", "star"), ("☆", "hollow star"),
                          ("✦", "sparkle"), ("✧", "hollow sparkle"),
                          ("✨", "sparkles"), ("\U0001f4ab", "dizzy star"))),
    ("Feelings", (("\U0001f4a2", "anger"), ("\U0001f4a6", "flustered"),
                  ("\U0001f4a7", "sweat drop"), ("⚡", "shock"),
                  ("\U0001f4a4", "sleep"), ("\U0001f300", "dizzy"),
                  ("☺", "smile"), ("☹", "frown"))),
    ("Music", (("♪", "note"), ("♫", "two notes"), ("♬", "beamed notes"),
               ("♩", "quarter note"))),
    ("Shouts", (("❗", "exclamation"), ("❕", "hollow exclamation"),
                ("‼", "double exclamation"), ("⁉", "shock question"),
                ("❓", "question"), ("❔", "hollow question"))),
    ("Other", (("☠", "skull"), ("✿", "flower"), ("❀", "hollow flower"))),
)

CHARS = tuple(ch for _g, items in PICKER for ch, _n in items)



def mask(name, size, hollow=0):
    """An 8-bit alpha mask of one mark, its INK `size` px tall.

    `hollow` > 0 draws it as an outline of that many px instead of filled,
    which is how ♡ relates to ♥.

    CROPPED TO THE INK, and that is not tidiness. The shapes are drawn in a
    100x100 box and they fill different amounts of it: a heart spans 6..90, a
    sweat drop 12..72. Returning the box meant every mark was scaled by its
    BOX rather than by its ink, so the drop came out two thirds the height of
    the heart beside it and looked like a smaller size of type. Cropping first
    makes `size` mean the same thing for all of them - which is what the
    caller in `typeset.mark_glyph` is asking for when it says "as tall as the
    capitals".
    """
    fills, holes = [], []
    for p in MARKS[name]:
        if isinstance(p, tuple) and len(p) == 2 and p[0] == "hole":
            holes.append(p[1])
        else:
            fills.append(p)
    n = max(8, int(size * SS * 1.2))
    im = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(im)

    def draw(p, ink):
        pts = [(x * n / 100.0, y * n / 100.0) for x, y in _flatten(p)]
        if hollow:
            d.line(pts + [pts[0]], fill=255,
                   width=max(1, int(round(hollow * SS * 1.2))), joint="curve")
        else:
            d.polygon(pts, fill=ink)

    for p in fills:
        draw(p, 255)
    # Holes AFTER every fill, because they erase: a skull's eye punched before
    # the jaw was laid down would be painted straight back over. Hollow mode
    # strokes them instead - the outline of a face keeps its eyes as rings.
    for p in holes:
        draw(p, 0)
    box = im.getbbox()
    if box:
        im = im.crop(box)
    h = max(1, int(round(size)))
    w = max(1, int(round(im.width * h / float(im.height))))
    return im.resize((w, h), Image.LANCZOS)
