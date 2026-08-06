"""Offline demo: everything except OCR and the LLM call.

Translations below are hand-written stand-ins so the detection -> inpaint ->
typeset -> render path can be exercised without network access. Line 8 is
deliberately long to stress the fit search.
"""
import cv2

from mangatl import inpaint, render, typeset
from mangatl.pipeline import RunConfig, detect_stage, load_page, report

MOCK = {
    0: ("Please... heal my illness, I'm begging you!", "Please, heal me!"),
    1: ("I was here first!", "Me first!"),
    2: ("I walked three days to get here!", "Three days I walked!"),
    3: ("My back... please, my back...!", "My back...!"),
    4: ("Lady Saint!!", "Saint!!"),
    5: ("Haa...", "Haa..."),
    6: ("Saint Leonora!!", "Leonora!!"),
    7: ("Crowded as ever...", "Packed as always."),
    8: ("The Founding Day Festival is their one real shot at a miracle. "
        "Of course they're desperate enough to kill for it.",
        "Festival miracles. Of course they're desperate."),
    9: ("Still, in a crowd this size someone is bound to get hurt.",
        "In this crowd, someone'll get hurt."),
}

page = load_page("page.png")
detect_stage(page, RunConfig(use_panels=False))

for r in page.ordered():
    if r.order in MOCK:
        r.dst_text, r.dst_compact = MOCK[r.order]

inpaint.inpaint_page(page)
cfg = typeset.TypesetConfig(font_path=typeset.default_font_path(), max_font=30, min_font=11)
typeset.typeset_page(page, cfg)

cv2.imwrite("out_clean.png", page.clean_plate)
cv2.imwrite("out_en.png", render.render_page(page, cfg))
render.render_reader(page, "page.png", "out_reader.html")

print(report(page))
print()
for r in page.ordered():
    lay = r.layout
    if not lay:
        continue
    tag = "COMPACT" if lay.used_compact else "       "
    ok = "" if lay.fit_ok else "  <-- OVERFLOW"
    print(f"[{r.order}] {tag} {lay.font_size:>2}pt x{len(lay.lines)}  "
          f"{' / '.join(lay.lines)}{ok}")
