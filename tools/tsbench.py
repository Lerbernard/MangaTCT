"""Typesetting bench — draw a sheet of bubbles and typeset them.

Not a test: an eyeball. Run it, open the PNG, and judge the typesetting the way
a reader would. Every bubble here is a shape that shows up on a real page —
tall ovals, wide ovals, near-circles, rectangles, tailed bubbles — paired with
a line of dialogue whose length is awkward for that shape.

    python3 tools/tsbench.py [out.png]
"""
from __future__ import annotations

import sys

import cv2
import numpy as np

sys.path.insert(0, ".")

from mangatl import render, typeset                       # noqa: E402
from mangatl.models import Page, TextRegion               # noqa: E402

# (w, h, text) — the shape of the bubble and what has to go in it.
CASES = [
    (150, 150, "WAIT."),
    (150, 150, "I DON'T UNDERSTAND."),
    (150, 150, "YOU'RE THE ONE WHO TOLD ME TO COME HERE IN THE FIRST PLACE."),
    (210, 120, "SO THAT'S WHAT YOU MEANT."),
    (210, 120, "IF WE LEAVE NOW WE MIGHT STILL MAKE THE LAST TRAIN HOME."),
    (110, 200, "IT'S NOT THAT SIMPLE."),
    (110, 200, "I'VE BEEN WAITING FOR SOMEONE TO SAY THAT OUT LOUD."),
    (260, 100, "HEY — ARE YOU LISTENING TO ME?"),
    (170, 170, "THE TRANSFER STUDENT? YEAH, SHE SHOWED UP THIS MORNING."),
    (170, 170, "STOP IT!"),
    (240, 160, "MY GRANDFATHER USED TO SAY THAT A MAN WHO RUNS FROM ONE "
               "FIGHT SPENDS THE REST OF HIS LIFE RUNNING."),
    (130, 130, "...HUH?"),
    (200, 130, "DON'T WORRY ABOUT IT — REALLY."),
    (200, 130, "UNBELIEVABLE"),
    (150, 220, "SHE ALREADY KNEW, DIDN'T SHE? THAT'S WHY SHE LEFT."),
    (280, 90, "WELCOME BACK, EVERYONE!"),
]

COLS = 4
GAP = 40


def ellipse_mask(w, h, kind="oval"):
    m = np.zeros((h, w), np.uint8)
    if kind == "rect":
        cv2.rectangle(m, (2, 2), (w - 3, h - 3), 255, -1)
    else:
        cv2.ellipse(m, (w // 2, h // 2), (w // 2 - 3, h // 2 - 3), 0, 0, 360,
                    255, -1)
    return m


def build() -> Page:
    cw = max(w for w, _, _ in CASES) + GAP
    ch = max(h for _, h, _ in CASES) + GAP
    rows = (len(CASES) + COLS - 1) // COLS
    W, H = COLS * cw + GAP, rows * ch + GAP
    img = np.full((H, W, 3), 210, np.uint8)          # grey so the bubble shows

    page = Page(image=img, source_path="bench")
    for i, (w, h, text) in enumerate(CASES):
        r, c = divmod(i, COLS)
        x = GAP + c * cw + (cw - GAP - w) // 2
        y = GAP + r * ch + (ch - GAP - h) // 2
        shape = "rect" if i % 8 == 7 else "oval"
        sub = ellipse_mask(w, h, shape)
        full = np.zeros((H, W), np.uint8)
        full[y:y + h, x:x + w] = sub
        img[full > 0] = 255                           # white bubble interior
        cont, _ = cv2.findContours(full, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, cont, -1, (30, 30, 30), 2)

        page.regions.append(TextRegion(
            id=i, bbox=(x, y, w, h), bubble_mask=full, bubble_bbox=(x, y, w, h),
            order=i, src_text="", dst_text=text))
    return page


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/tsbench.png"
    page = build()
    cfg = typeset.TypesetConfig(font_path="fonts/CCWildWords.ttf")
    typeset.typeset_page(page, cfg)
    img = render.render_page(page, cfg)
    cv2.imwrite(out, img)
    for r in page.ordered():
        lay = r.layout
        print("%2d %3dx%-3d %2dpt lead %.2f  %s%s"
              % (r.id, r.bbox[2], r.bbox[3], lay.font_size, lay.leading,
                 " / ".join(lay.lines),
                 ("   [%s]" % r.flagged) if r.flagged else ""))
    print("->", out)


if __name__ == "__main__":
    main()
