#!/usr/bin/env python3
"""The card that goes at the end of a chapter.

lee: *"creat a advertizement card that i can put at the end of chapters telling
peoplw that the chapter was tranlated with mangatct and to visit mangatct if
they wan to translate something themselves"*.

Six files, from one description each: three shapes by two grounds.

    page     1400 x 2000   the shape of a manga page, dropped in as a last page
    strip     800 x 1000   webtoon width, sitting at the foot of the strip
    banner   1400 x  500   wide and short, pasted under the last panel

    dark     the app's own black and gold, an obvious credits card
    light    white paper, black type, one gold rule, quiet at the end of a
             black-and-white chapter

Everything is drawn, nothing is fetched: the mark is the same polygon the site
and the app icon use, read out of `site/assets/mark.svg` rather than copied, so
one shape stays one shape. The display face is Anton, which is what the site
sets its headings in.

    python tools/adcard.py                  # write all six into out/adcards
    python tools/adcard.py --out somewhere

A card at the end of a chapter is read for about a second and a half by
somebody who has just finished a story. So: one sentence saying what made it,
one line saying where to go, and nothing else asking for attention. There is no
"click here", no list of features and no logo wall. The address IS the call to
action, and it is the biggest thing on the card after the name.
"""
import argparse
import os
import re

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ANTON = os.path.join(ROOT, "fonts", "Anton-Regular.ttf")
BODY = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BODY_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MARK_SVG = os.path.join(ROOT, "site", "assets", "mark.svg")

# ------------------------------------------------------------------- the words
#
# Written to be read by somebody who has just closed a chapter, not by somebody
# shopping for software.

SAYS = "This chapter was translated with"
NAME = ("Manga", "TCT")
LINE = ("Find the text, read it, translate it, clean the page "
        "and typeset it. Every decision stays yours.")
FORMATS = "Manga  |  manhwa  |  manhua"
GO = "Translate your own at"
URL = "mangatct.com"

# ------------------------------------------------------------------ the palette

DARK = dict(bg=(11, 13, 18), ink=(233, 237, 244), dim=(148, 161, 181),
            rule=(38, 48, 64), gold=(255, 196, 0), gold2=(255, 157, 0),
            on_gold=(32, 24, 10), panel=(20, 25, 34))
LIGHT = dict(bg=(255, 255, 255), ink=(17, 21, 28), dim=(92, 103, 121),
             rule=(221, 227, 236), gold=(255, 179, 0), gold2=(255, 143, 0),
             on_gold=(36, 26, 4), panel=(246, 247, 250))

SHAPES = {"page": (1400, 2000), "strip": (800, 1000), "banner": (1400, 500)}


# ---------------------------------------------------------------------- the mark

def mark_points():
    """The M, out of `mark.svg`, as a list of points in its 64x64 box.

    Read rather than copied. The same shape is the site's header, the app icon
    and the coin, and a second copy of it here is a second thing to remember
    when it changes. The path is straight lines only, which is what makes this
    six lines instead of an SVG library.
    """
    d = re.search(r'\sd="([^"]+)"', open(MARK_SVG, encoding="utf-8").read())
    if not d:
        raise SystemExit("mark.svg has no path in it")
    nums = re.findall(r"-?\d+(?:\.\d+)?", d.group(1))
    xy = [float(n) for n in nums]
    return list(zip(xy[0::2], xy[1::2]))


def gradient(size, a, b, angle=160):
    """A linear gradient the size of a box. `angle` is roughly the CSS one:
    160 degrees is the top-left-to-bottom-right sweep the site uses."""
    w, h = size
    img = Image.new("RGB", (w, h))
    px = img.load()
    import math
    rad = math.radians(angle - 90)
    dx, dy = math.cos(rad), math.sin(rad)
    span = abs(dx) * w + abs(dy) * h or 1
    for y in range(h):
        for x in range(w):
            t = ((x - (w if dx < 0 else 0)) * dx
                 + (y - (h if dy < 0 else 0)) * dy) / span
            t = min(1.0, max(0.0, t))
            px[x, y] = (round(a[0] + (b[0] - a[0]) * t),
                        round(a[1] + (b[1] - a[1]) * t),
                        round(a[2] + (b[2] - a[2]) * t))
    return img


def draw_mark(img, box, pal):
    """The mark, filled with the gold gradient, at 4x and scaled down.

    Drawn big and shrunk because PIL's polygon has no antialiasing: at the size
    this sits on the card, the diagonals of an M are the whole shape.
    """
    x, y, size = box
    up = 4
    big = Image.new("L", (size * up, size * up), 0)
    ImageDraw.Draw(big).polygon(
        [(px / 64 * size * up, py / 64 * size * up) for px, py in mark_points()],
        fill=255)
    mask = big.resize((size, size), Image.LANCZOS)
    img.paste(gradient((size, size), pal["gold"], pal["gold2"]), (x, y), mask)


# ---------------------------------------------------------------------- helpers

def fit(font_path, text, want_w, start, floor=8):
    """The largest size at which `text` fits `want_w`. The cards are three
    different widths and the words are the same, so every headline is measured
    rather than set."""
    size = start
    while size > floor:
        f = ImageFont.truetype(font_path, size)
        if f.getlength(text) <= want_w:
            return f
        size -= 1
    return ImageFont.truetype(font_path, floor)


def wrap(draw, text, font, width):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def centre(draw, text, font, y, width, fill, x0=0):
    w = draw.textlength(text, font=font)
    draw.text((x0 + (width - w) / 2, y), text, font=font, fill=fill)
    return y + font.size


def wordmark(draw, y, width, pal, size, x0=0):
    """`Manga` in the ink colour and `TCT` in gold, centred as one word.

    One word, so the two halves are measured together and drawn touching. The
    site had this wrong once: a flex gap meant to sit between the mark and the
    name was also splitting the name in half.
    """
    f = ImageFont.truetype(ANTON, size)
    a, b = NAME
    wa, wb = draw.textlength(a, font=f), draw.textlength(b, font=f)
    x = x0 + (width - (wa + wb)) / 2
    draw.text((x, y), a, font=f, fill=pal["ink"])
    draw.text((x + wa, y), b, font=f, fill=pal["gold"])
    return y + size


# ------------------------------------------------------------------- the cards

def card(shape, pal, dark):
    w, h = SHAPES[shape]
    img = Image.new("RGB", (w, h), pal["bg"])
    d = ImageDraw.Draw(img)
    banner = shape == "banner"

    # A gold rule across the top. On the dark card it is the thing that says
    # "this is not part of the chapter"; on the light one it is the only
    # colour, which is why it is thin.
    bar = max(4, w // 190) if dark else max(3, w // 300)
    img.paste(gradient((w, bar), pal["gold"], pal["gold2"], 90), (0, 0))

    pad = int(w * (0.07 if banner else 0.10))
    inner = w - pad * 2

    if banner:
        # Wide and short: the mark on the left, three rows beside it. Stacking
        # this the way the tall cards stack would leave a card that is all
        # margin, and putting the address on the same line as the name put the
        # descender of `g` through it.
        f_says = fit(BODY, SAYS, w * 0.5, int(h * 0.090))
        nsize = int(h * 0.26)
        f_name = ImageFont.truetype(ANTON, nsize)
        f_go = fit(BODY, GO, w * 0.34, int(h * 0.085))

        msize = int(h * 0.46)
        left = pad + msize + int(w * 0.035)
        # The address is fitted to what is LEFT after the words in front of it,
        # not to a share of the card. Fitted to a share, it ran off the right
        # edge the moment the phrase before it grew.
        ux = left + f_go.getlength(GO + "  ")
        f_url = fit(ANTON, URL, w - pad - ux, int(h * 0.190))

        say_h = f_says.getbbox(SAYS)[3]
        name_h = f_name.getbbox(NAME[0] + NAME[1])[3]
        go_h = max(f_go.getbbox(GO)[3], f_url.getbbox(URL)[3])
        g1, g2 = int(h * 0.030), int(h * 0.055)
        tall = say_h + g1 + name_h + g2 + go_h

        draw_mark(img, (pad, (h - msize) // 2 + bar // 2, msize), pal)

        y = (h - tall) // 2 + bar // 2
        d.text((left, y), SAYS, font=f_says, fill=pal["dim"])
        y += say_h + g1

        a, b = NAME
        d.text((left, y), a, font=f_name, fill=pal["ink"])
        d.text((left + d.textlength(a, font=f_name), y), b, font=f_name,
               fill=pal["gold"])
        y += name_h + g2

        # The two halves of the last line sit on one baseline, which means the
        # smaller one is dropped by the difference in their heights rather than
        # both being hung from the same top edge.
        d.text((left, y + go_h - f_go.getbbox(GO)[3]), GO, font=f_go,
               fill=pal["dim"])
        d.text((ux, y + go_h - f_url.getbbox(URL)[3]), URL, font=f_url,
               fill=pal["gold"])
        return img

    # Page and strip: one column, measured first and then drawn.
    #
    # Measured first because the pieces are sized off the card's width and the
    # card's height is not a multiple of its width: laying this out by adding
    # gaps as it went ran the address off the bottom of the page card while
    # leaving the strip card half empty. So every piece says how tall it is,
    # the column is centred in what is left after the margins, and the same
    # description fits both shapes.
    msize = int(w * 0.20)
    f_says = fit(BODY, SAYS, inner, int(w * 0.048))
    nsize = int(w * 0.135)
    f_fmt = fit(BODY_B, FORMATS, inner, int(w * 0.032))
    f_line = ImageFont.truetype(BODY, int(w * 0.036))
    rows = wrap(d, LINE, f_line, inner * 0.92)
    f_go = fit(BODY, GO, inner, int(w * 0.040))
    f_url = fit(ANTON, URL, inner * 0.86, int(w * 0.115))
    uw = d.textlength(URL, font=f_url)
    # The light card underlines the address instead of plating it, and the rule
    # has to clear the descenders of `g`: at `size * 1.12` it ran straight
    # through them. Measured off the glyphs, like the wordmark above.
    url_drop = f_url.getbbox(URL)[3]
    rule_w = max(2, w // 450)
    under = url_drop + int(f_url.size * 0.10) + rule_w
    plate_h = int(f_url.size * 1.62) if dark else under + int(h * 0.008)

    gap = int(h * 0.030)
    block = [
        (msize, "mark"),
        (int(h * 0.045), None),
        (int(f_says.size * 1.05), "says"),
        (int(h * 0.014), None),
        # Anton's descender falls well past its nominal size, so the row is
        # measured off the glyphs rather than off the number: at `nsize` the
        # `g` of Manga sat on top of the line under it.
        (ImageFont.truetype(ANTON, nsize).getbbox(NAME[0] + NAME[1])[3],
         "name"),
        (int(h * 0.020), None),
        (int(f_fmt.size * 1.4), "formats"),
        (gap + int(h * 0.012), None),
        (max(1, w // 700), "rule"),
        (gap + int(h * 0.012), None),
    ]
    for i, _row in enumerate(rows):
        block.append((int(f_line.size * 1.42), ("line", i)))
    block += [
        (int(h * 0.038), None),
        (int(f_go.size * 1.25), "go"),
        (int(h * 0.014), None),
        (plate_h, "url"),
    ]

    tall = sum(n for n, _what in block)
    floor = int(h * 0.085)

    # If the column is taller than the card, the GAPS give way and the type
    # does not. Squeezing the words instead would make one shape's card read at
    # a different size from another's, and these are meant to be one card in
    # three shapes. The strip is the one that needs it: the same words in three
    # quarters of the height.
    room = h - floor * 2
    if tall > room:
        spare = sum(n for n, what in block if what is None)
        keep = max(0.0, (room - (tall - spare)) / spare) if spare else 0.0
        block = [(n if what else int(n * keep), what) for n, what in block]
        tall = sum(n for n, _what in block)

    y = max(floor, (h - tall) // 2)

    for step, what in block:
        if what == "mark":
            draw_mark(img, ((w - msize) // 2, int(y), msize), pal)
        elif what == "says":
            centre(d, SAYS, f_says, y, inner, pal["dim"], pad)
        elif what == "name":
            wordmark(d, y, inner, pal, nsize, pad)
        elif what == "formats":
            centre(d, FORMATS, f_fmt, y, inner, pal["gold"], pad)
        elif what == "rule":
            # The half above is a credit and the half below is an invitation.
            # Two different things being said, so there is a line between them.
            d.line([(pad + inner * 0.28, y), (pad + inner * 0.72, y)],
                   fill=pal["rule"], width=max(1, w // 700))
        elif isinstance(what, tuple) and what[0] == "line":
            centre(d, rows[what[1]], f_line, y, inner, pal["dim"], pad)
        elif what == "go":
            centre(d, GO, f_go, y, inner, pal["dim"], pad)
        elif what == "url":
            # The address IS the call to action, so it is the biggest thing on
            # the card after the name. On the dark one it sits in a gold plate:
            # at a phone's width a line of gold type on black is a line of
            # text, and a plate is a button.
            if dark:
                px = int(w * 0.055)
                bw, bh = int(uw + px * 2), plate_h
                plate = gradient((bw, bh), pal["gold"], pal["gold2"])
                rounded = Image.new("L", (bw, bh), 0)
                ImageDraw.Draw(rounded).rounded_rectangle(
                    [0, 0, bw - 1, bh - 1], radius=bh // 4, fill=255)
                img.paste(plate, ((w - bw) // 2, int(y)), rounded)
                d.text(((w - uw) / 2, y + (bh - f_url.size * 1.22) / 2),
                       URL, font=f_url, fill=pal["on_gold"])
            else:
                centre(d, URL, f_url, y, inner, pal["gold"], pad)
                yy = y + under - rule_w
                d.line([((w - uw) / 2, yy), ((w + uw) / 2, yy)],
                       fill=pal["gold"], width=rule_w)
        y += step

    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "adcards"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    made = []
    for shape in SHAPES:
        for name, pal in (("dark", DARK), ("light", LIGHT)):
            path = os.path.join(args.out, f"mangatct-{shape}-{name}.png")
            card(shape, pal, name == "dark").save(path)
            made.append(path)
    for p in made:
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
