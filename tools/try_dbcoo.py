"""Run the two-specialist manga route over a folder and draw what it found.

Nothing in the app selects this route yet, so this is how to look at it.

    python tools/try_dbcoo.py  <folder of pages>  [output folder]

It reads the weights from the same places the app would:

    comictextdetector.pt.onnx   beside this checkout, for the CLEAN MASK
    detect-20241225.ckpt        manga-image-translator's DBNet
    dbpp_coo.dat                the DB++ finetune on COO

...and any of the three can be pointed somewhere else:

    set MANGATL_CTD=C:\\path\\to\\comictextdetector.pt.onnx
    set MANGATL_DBNET=C:\\path\\to\\detect-20241225.ckpt
    set MANGATL_COO=C:\\path\\to\\dbpp_coo.dat

Each page comes out as a PNG with the boxes on it, coloured by kind, and the
run prints the count and the seconds. Expect about ten seconds a page on a
laptop CPU -- three models, and one of them read twice.
"""
import os
import sys
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(HERE))

from mangatl.models import Page                          # noqa: E402
from mangatl.detect import dbcoo                         # noqa: E402

COL = {"bubble": (60, 60, 235), "narration": (200, 60, 200),
       "freefloat": (40, 190, 40), "sfx": (235, 160, 30)}
NAME = {"bubble": "bubble", "narration": "narration",
        "freefloat": "outside text", "sfx": "sound effect"}


def _find(env, *names):
    got = os.environ.get(env)
    if got:
        return got
    for n in names:
        for d in (HERE, os.path.expanduser("~/Downloads/detector"),
                  os.path.expanduser("~/Downloads")):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return ""


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    src = argv[0]
    dst = argv[1] if len(argv) > 1 else os.path.join(src, "_dbcoo")
    ctd = _find("MANGATL_CTD", "comictextdetector.pt.onnx")
    db = _find("MANGATL_DBNET", "detect-20241225.ckpt", "detect.ckpt")
    coo = _find("MANGATL_COO", "dbpp_coo.dat", "dbpp_coo.pth",
                "DB_finetune_COO")
    print("comic-text-detector : %s" % (ctd or "NOT FOUND"))
    print("DBNet               : %s" % (db or "NOT FOUND"))
    print("DB++ / COO          : %s" % (coo or "NOT FOUND"))
    why = dbcoo.why_not(ctd, db, coo)
    if why:
        print("\ncannot run: %s" % why)
        return 1

    os.makedirs(dst, exist_ok=True)
    pages = sorted(f for f in os.listdir(src)
                   if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))
    if not pages:
        print("no pages in %s" % src)
        return 1
    print("\n%d pages -> %s\n" % (len(pages), dst))
    t0 = time.time()
    total = 0
    for n in pages:
        img = cv2.imread(os.path.join(src, n))
        if img is None:
            continue
        t = time.time()
        regions = dbcoo.detect(Page(image=img), ctd, db, coo)
        total += len(regions)
        shot = img.copy()
        for r in regions:
            x, y, w, h = [int(v) for v in r.bbox]
            cv2.rectangle(shot, (x, y), (x + w, y + h),
                          COL.get(r.kind, (0, 0, 255)), 3)
        bar = np.full((34, shot.shape[1], 3), 255, np.uint8)
        cv2.putText(bar, "%s   %d boxes   %.1fs" % (n, len(regions),
                                                    time.time() - t),
                    (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1,
                    cv2.LINE_AA)
        cv2.imwrite(os.path.join(dst, os.path.splitext(n)[0] + ".png"),
                    np.vstack([bar, shot]))
        print("  %-16s %3d boxes  %5.1fs   %s"
              % (n, len(regions), time.time() - t,
                 "  ".join(sorted({NAME.get(r.kind, r.kind)
                                   for r in regions}))), flush=True)
    print("\n%d boxes over %d pages, %.1f s/page"
          % (total, len(pages), (time.time() - t0) / len(pages)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
