"""CLI:  python -m mangatl page.png -o out/ --context series.json"""
from __future__ import annotations

import argparse
import glob
import os
import sys

from .pipeline import RunConfig, report, run
from .translate import SeriesContext


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="mangatl", description="Manga translation pipeline")
    p.add_argument("inputs", nargs="+", help="image files, globs, or a directory")
    p.add_argument("-o", "--outdir", default="out")
    p.add_argument("--context", default="", help="series context/glossary JSON (read+written)")
    p.add_argument("--detector", choices=["classical", "yolo"], default="classical")
    p.add_argument("--weights", default="")
    p.add_argument("--font", default="")
    p.add_argument("--uppercase", action="store_true")
    p.add_argument("--min-font", type=int, default=12)
    p.add_argument("--max-font", type=int, default=34)
    p.add_argument("--panels", action="store_true")
    p.add_argument("--no-translate", action="store_true", help="detect + OCR only")
    p.add_argument("--reader-only", action="store_true", help="skip inpaint/typeset")
    p.add_argument("--debug", action="store_true")
    a = p.parse_args(argv)

    paths: list[str] = []
    for i in a.inputs:
        if os.path.isdir(i):
            for ext in ("png", "jpg", "jpeg", "webp"):
                paths += sorted(glob.glob(os.path.join(i, f"*.{ext}")))
        else:
            paths += sorted(glob.glob(i)) or [i]
    if not paths:
        print("no input images", file=sys.stderr)
        return 1

    cfg = RunConfig(
        detector=a.detector, weights=a.weights, use_panels=a.panels,
        translate=not a.no_translate,
        inpaint=not a.reader_only, typeset=not a.reader_only,
        debug_overlay=a.debug, font=a.font, uppercase=a.uppercase,
        min_font=a.min_font, max_font=a.max_font,
    )
    ctx = SeriesContext.load(a.context) if a.context else SeriesContext()

    for path in paths:
        page = run(path, a.outdir, cfg, ctx=ctx)
        print(f"{os.path.basename(path)}: {report(page)}")
        for r in page.ordered():
            if r.flagged:
                print(f"    [{r.order}] {r.flagged.strip()} :: {r.src_text[:24]}")

    if a.context:
        ctx.save(a.context)
    print(f"\nwrote to {a.outdir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
