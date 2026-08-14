"""Why Find text missed a sound effect on THIS page.

Run it and it prints what each part of the detector saw on the pages of the
chapter that is open, so the next change is measured instead of guessed:

    python tools/why_missed.py                # every page of the open chapter
    python tools/why_missed.py 21 28          # just those page numbers
    python tools/why_missed.py some/page.png  # or a file, if you have one

With no file it asks the PROJECT where its pages are rather than guessing at a
folder. A re-cut webtoon does not live in `out/input` — when the chapter came
from somebody else's folder the pages are written to `out/strip` instead, and
"cannot be read" is what you get for guessing.

    --output somewhere       if the editor was started with --output somewhere

What it prints, per page:

* **blocks** — what the model's box head proposed, at four confidences. If the
  count is 0 at 0.05, the box head cannot see the effect at all and no
  threshold will help.
* **mask** — how much of the page the segmentation mask claims, at four floors.
  This is what the coverage pass has to work with. If the mask does not cover a
  sound effect, nothing downstream can find it.
* **leftover marks** — the ink the box head did NOT claim, biggest first, with
  each mark's size and how much ink it carries. These are the pieces the
  coverage pass tries to group.
* **the gates** — for every pair of leftover marks that is CLOSE to joining,
  the sideways gap, the vertical gap, and both as multiples of the smaller
  mark. That is the exact number `join_x` and `join_y` are compared against, so
  a pair that should have joined and did not is right there with its answer.

Nothing is written and nothing is changed. It reads the same model the app
reads, from the same place.
"""
from __future__ import annotations

import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from mangatl import imgio                                   # noqa: E402
from mangatl.detect import comictext as CT                  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(HERE, "comictextdetector.pt.onnx")


def heads(img, tune):
    net = CT._get_net(MODEL)
    h, w = img.shape[:2]
    lb, dw, dh = CT._letterbox(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), CT.INPUT)
    net.setInput(cv2.dnn.blobFromImage(lb, 1 / 255.0, (CT.INPUT, CT.INPUT)))
    names = net.getUnconnectedOutLayersNames()
    outs = dict(zip(names, net.forward(names)))
    seg = np.asarray(outs["seg"]).squeeze()
    seg = seg[:CT.INPUT - dh, :CT.INPUT - dw]
    seg = cv2.resize(seg, (w, h), interpolation=cv2.INTER_LINEAR)
    rr_x = w / max(1, CT.INPUT - dw)
    rr_y = h / max(1, CT.INPUT - dh)

    def blocks(th):
        out = []
        for x1, y1, x2, y2, cf in CT._decode_blocks(outs["blk"], th,
                                                    tune["nms_thresh"]):
            X1, Y1 = max(0, int(x1 * rr_x)), max(0, int(y1 * rr_y))
            X2, Y2 = min(w - 1, int(x2 * rr_x)), min(h - 1, int(y2 * rr_y))
            if X2 - X1 >= 4 and Y2 - Y1 >= 4:
                out.append((X1, Y1, X2, Y2, round(float(cf), 3)))
        return out
    return seg, blocks


def one(path, tune, pairs=14, marks=12):
    img = imgio.imread(path)
    if img is None:
        print("%s: cannot be read" % path)
        return
    h, w = img.shape[:2]
    seg, blocks = heads(img, tune)
    print("\n=== %s  %dx%d" % (os.path.basename(path), w, h))

    at = {th: blocks(th) for th in (tune["conf_thresh"], 0.10, 0.05)}
    print("  blocks: " + "  ".join("conf>%.2f: %d" % (th, len(v))
                                   for th, v in sorted(at.items())))
    print("  mask:   " + "  ".join(
        "keep>%.2f: %.2f%% of the page" % (th, 100 * (seg > th).mean())
        for th in (tune["mask_thresh"], 0.10, 0.05)))

    claimed = np.zeros((h, w), bool)
    for X1, Y1, X2, Y2, _cf in at[tune["conf_thresh"]]:
        claimed[Y1:Y2 + 1, X1:X2 + 1] = True
    tmask = ((seg > tune["mask_thresh"]).astype(np.uint8) * 255)

    P, _lab = CT._pieces((tmask > 0) & ~claimed)
    P = sorted(P, key=lambda d: -d["ink"])
    print("  leftover marks: %d" % len(P))
    for d in P[:marks]:
        print("     (%4d,%4d)-(%4d,%4d)  ink %6d  size %4d"
              % (d["x0"], d["y0"], d["x1"], d["y1"], d["ink"], d["sz"]))

    jx = tune.get("join_x") or 0
    jy = tune.get("join_y") or 0
    print("  near-misses (join_x=%s join_y=%s):" % (jx or "circle", jy or "-"))
    rows = []
    for i in range(len(P)):
        for j in range(i + 1, len(P)):
            a, b = P[i], P[j]
            gx = max(0, max(a["x0"], b["x0"]) - min(a["x1"], b["x1"]))
            gy = max(0, max(a["y0"], b["y0"]) - min(a["y1"], b["y1"]))
            s = min(a["sz"], b["sz"])
            rx, ry = gx / s, gy / s
            joined = (rx <= jx and ry <= jy) if (jx and jy) else \
                ((gx * gx + gy * gy) ** 0.5 <= CT.LEFT_NEAR * s)
            if rx <= 4 and ry <= 4:
                rows.append((joined, round(max(rx, ry), 2), gx, gy, s,
                             (a["x0"], a["y0"]), (b["x0"], b["y0"])))
    rows.sort(key=lambda r: r[1])
    for joined, _m, gx, gy, s, aa, bb in rows[:pairs]:
        print("     %s gx=%4d gy=%4d smaller=%4d -> x %.2f  y %.2f   %s %s"
              % ("JOINED " if joined else "refused", gx, gy, s,
                 gx / s, gy / s, aa, bb))

    got = CT._harvest(tmask, claimed,
                      near_x=tune.get("join_x"), near_y=tune.get("join_y"))
    print("  groups kept: %d" % len(got))
    for (x0, y0, x1, y1), _sub, ink in got:
        print("     (%4d,%4d)-(%4d,%4d) ink %d" % (x0, y0, x1, y1, ink))


def _candidates(first):
    """Every folder that looks like it holds a project, biggest chapter first.

    The editor is started with `--output`, and that is not written down
    anywhere this tool can read. Rather than make somebody remember which one
    they used, look in the obvious places and say what was found.
    """
    seen, out = set(), []
    roots = [first, "out", os.path.join(HERE, "out"),
             os.path.join(os.path.dirname(HERE), "out")]
    roots += sorted(glob.glob(os.path.join(os.path.dirname(HERE), "*", "project.json")))
    roots += sorted(glob.glob(os.path.join(HERE, "*", "project.json")))
    for r in roots:
        if r.endswith("project.json"):
            r = os.path.dirname(r)
        r = os.path.abspath(r)
        if r in seen or not os.path.isfile(os.path.join(r, "project.json")):
            continue
        seen.add(r)
        try:
            p, pages = _open_chapter(r)
        except Exception:
            continue
        out.append((len(pages), r, p, pages))
    out.sort(reverse=True)
    return out


def _open_chapter(out_dir):
    """The pages of the project as the APP has them, which is the only place
    that knows where a re-cut chapter ended up."""
    from mangatl.project import Project

    p = Project(None, out_dir)
    return p, [pg.path for pg in p.pages]


def main(argv):
    out_dir = "out"
    if "--output" in argv:
        k = argv.index("--output")
        out_dir = argv[k + 1] if k + 1 < len(argv) else "out"
        del argv[k:k + 2]

    files, medium = [], os.environ.get("MEDIUM", "")
    picks = [a for a in argv if a.isdigit()]
    paths = [a for a in argv if not a.isdigit()]

    if not paths:
        found = _candidates(out_dir)
        if not found:
            print("no project.json found. Point me at the editor's --output "
                  "folder:  python tools/why_missed.py --output ..\\out 21 28")
            return 2
        if len(found) > 1:
            print("projects found:")
            for n, r, _p, _pg in found:
                print("   %-4d pages   %s" % (n, r))
        n, root, proj, pages = found[0]
        medium = medium or proj.medium
        print("using: %s  (%d pages, %s)" % (root, n, medium))
        if picks:
            bad = [k for k in picks if not (1 <= int(k) <= n)]
            if bad:
                print("this chapter has %d pages, so %s %s no page here."
                      % (n, ", ".join(bad), "are" if len(bad) > 1 else "is"))
        files = ([pages[int(k) - 1] for k in picks if 1 <= int(k) <= n]
                 if picks else pages)
        if not files:
            print("nothing to look at.")
            return 2
    else:
        for a in paths:
            files += sorted(glob.glob(a)) or [a]

    tune = CT.tuning_for(medium or "manhwa")
    print("format: %s   %s" % (medium or "manhwa", tune))
    if not os.path.isfile(MODEL):
        print("model not found beside the app: %s" % MODEL)
        return 2
    missing = [f for f in files if not os.path.isfile(f)]
    if missing:
        print("not on disk: %s" % ", ".join(missing[:4]))
    for f in files:
        if os.path.isfile(f):
            one(f, tune)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
