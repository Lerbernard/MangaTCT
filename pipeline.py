"""Stage orchestration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import cv2

from . import inpaint as inpaint_mod
from . import order as order_mod
from . import render as render_mod
from . import typeset as typeset_mod
from .detect import classical
from .translate import SeriesContext, translate_page
from .models import Page
from . import imgio


@dataclass
class RunConfig:
    detector: str = "classical"        # classical | yolo
    weights: str = ""
    use_panels: bool = False           # classical panel detection is rough
    translate: bool = True
    inpaint: bool = True
    typeset: bool = True
    reader: bool = True
    debug_overlay: bool = False
    font: str = ""
    uppercase: bool = False
    max_font: int = 34
    min_font: int = 12


def load_page(path: str) -> Page:
    img = imgio.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        from PIL import Image
        import numpy as np
        img = cv2.cvtColor(np.array(Image.open(path).convert("RGB")), cv2.COLOR_RGB2BGR)
    return Page(image=img, source_path=os.path.basename(path))


def detect_stage(page: Page, cfg: RunConfig) -> None:
    if cfg.detector == "yolo":
        from .detect import yolo
        page.regions = yolo.detect(page, cfg.weights)
    else:
        page.regions = classical.detect(page)
    if cfg.use_panels:
        page.panels = classical.detect_panels(page)
        order_mod.assign_panels(page)
    order_mod.assign_order(page)


def run(path: str, outdir: str, cfg: RunConfig | None = None,
        ctx: Optional[SeriesContext] = None, client=None) -> Page:
    cfg = cfg or RunConfig()
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]

    page = load_page(path)
    detect_stage(page, cfg)

    if page.regions:
        from .ocr import ocr_page
        ocr_page(page)

    if cfg.translate and page.regions:
        translate_page(page, ctx=ctx, client=client)

    if cfg.inpaint:
        inpaint_mod.inpaint_page(page)

    tcfg = typeset_mod.TypesetConfig(
        font_path=cfg.font or "", uppercase=cfg.uppercase,
        max_font=cfg.max_font, min_font=cfg.min_font,
    )
    if cfg.typeset:
        typeset_mod.typeset_page(page, tcfg)
        out = render_mod.render_page(page, tcfg, debug=cfg.debug_overlay)
        imgio.imwrite(os.path.join(outdir, f"{stem}_en.png"), out)

    if cfg.reader:
        src = f"{stem}_src.png"
        imgio.imwrite(os.path.join(outdir, src), page.image)
        render_mod.render_reader(page, src, os.path.join(outdir, f"{stem}_reader.html"))

    with open(os.path.join(outdir, f"{stem}.json"), "w", encoding="utf-8") as fh:
        fh.write(page.to_json())

    return page


def report(page: Page) -> str:
    flagged = [r for r in page.regions if r.flagged]
    shrunk = [r for r in page.regions if r.layout and r.layout.used_compact]
    bad = [r for r in page.regions if r.layout and not r.layout.fit_ok]
    return (
        f"{len(page.regions)} regions | {len(shrunk)} used compact wording | "
        f"{len(bad)} overflowed | {len(flagged)} flagged for review"
    )
