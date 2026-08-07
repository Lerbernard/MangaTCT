#!/usr/bin/env python3
"""Break the code on purpose and see whether the tests notice.

A test that passes proves nothing on its own — it passes against the right
code and, far too often, against the wrong code as well. So each mutation
below is a small, plausible wrong version of a line that was just written: a
guard dropped, a comparison flipped, a field left unset. The tests are run
against it. A mutation the tests still pass is a **survivor**, and it means
one of two things, both worth knowing:

* the behaviour is not tested — write the test; or
* the line does not matter — take it out.

    python tools/mutate.py --list
    python tools/mutate.py                 # every mutation in the set
    python tools/mutate.py -k manual       # just the ones named `manual*`

The original file is put back in a `finally`, so an interrupted run does not
leave a mutant behind. **Do not kill this process with `pkill`** — that skips
the restore, and everything measured afterwards is measured against a mutant.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# `tools/` sits inside the package, so one level up IS the package — the
# folder holding `editor.py`, `static/` and `tests/`. The parent of that is
# what has to be on `sys.path` for `import mangatl` to work, and it is passed
# to the test run rather than assumed, so this works from any directory and in
# a checkout laid out either way.
PKG = Path(__file__).resolve().parents[1]
ROOT = PKG.parent

# (name, file, find, replace, test files)
PY = "editor.py"
MAN = "manual.py"
JS = "static/js/pipeline.js"
T_MAN = ["tests/test_translating_it_yourself.py"]
T_FONT = ["tests/test_pipeline.py", "tests/test_your_own_fonts.py"]
T_SPILL = ["tests/test_out_of_the_box.py"]
TS = "typeset.py"
BUN = "bundle.py"
T_TCTP = ["tests/test_a_chapter_in_one_file.py"]
HTML = "static/editor.html"
PICK = "pickdir.py"
ICON = "tools/make_icon.py"
T_MARK = ["tests/test_the_dialog_wears_our_own_mark.py"]
T_HEAL = ["tests/test_healing_brush.py", "tests/test_the_toolbox.py",
          "tests/test_clean_says_when_it_fails.py"]
STR = "strip.py"
PRJ = "project.py"
T_STRIP = ["tests/test_the_strip_is_not_a_page.py"]
TR = "translate.py"
T_DOTS = ["tests/test_no_pause_the_page_never_drew.py"]
OCR = "ocr.py"
T_BOX = ["tests/test_which_box_the_words_are_in.py"]
JSP = "static/js/project.js"
T_KEPT = ["tests/test_a_run_that_fell_over_kept_its_pages.py"]
T_DASH = ["tests/test_breaking_at_the_authors_dashes.py",
          "tests/test_out_of_the_box.py"]
COIN = "coins.py"
JSC = "static/js/coins.js"
T_COIN = ["tests/test_what_it_costs_in_coins.py"]
ACC = "account.py"
TYP = "typeset.py"
T_FONTPATH = ["tests/test_your_own_fonts.py"]
T_ACC = ["tests/test_the_account_the_coins_live_in.py"]
T_STEP = ["tests/test_per_step_models.py", "tests/test_model_gone.py",
          "tests/test_no_more_same_as.py"]

# ---- the rebuild of 6 August: the bill, the context, the estimate that
# learns, the three services, one key each, and a job strip that holds still.
CSS = "static/css/editor.css"
PIPE = "static/js/pipeline.js"
T_CTX = ["tests/test_pipeline.py", "tests/test_what_it_costs_in_coins.py"]
T_GLOSS = ["tests/test_every_term_says_what_it_is.py"]
T_LEARN = ["tests/test_the_estimate_learns.py"]
T_MENU = ["tests/test_a_menu_you_can_trust.py"]
T_KEYS = ["tests/test_one_key_per_service.py"]
T_BAR = ["tests/test_the_bar_holds_its_width.py"]
T_WORD = ["tests/test_the_word_is_typesetting.py"]

# The landing page. `T_SITE` is the CONTENT test only — not the one that asks
# whether index.html has been rebuilt, which every mutation here would trip
# for the same uninteresting reason and which would make the whole set say
# nothing. See `tests/test_the_website_is_built.py` for why they are apart.
SITE = "site/build.py"
T_SITE = ["tests/test_the_website.py"]
T_STORY = ["tests/test_the_story_switches.py"]
T_TRIM = ["tests/test_a_menu_you_can_trust.py", "tests/test_per_step_models.py",
          "tests/test_model_gone.py"]
T_MANUAL = ["tests/test_translating_it_yourself.py"]

# The hand-run seeding script. Not executed by any test — it wants a
# Firestore — so what is held is its source, and the property held is an
# ordering: refuse before you write.
SEED = "firebase/functions/seed.js"
T_SEED = ["tests/test_the_website.py"]

# The four pages a customer sees, and the numbers on them. `T_LOOK` runs the
# browser file as well as the source one: half of what matters here is only
# true once a browser has painted it.
ACC = "site/account.html"
SCSS = "site/style.css"
APPJS = "site/app.js"
COSTS = "site/costs.js"
T_LOOK = ["tests/test_the_site_pages.py", "tests/test_the_website.py"]

MUTANTS = [
    # ---- the file that goes out
    ("manual-label-drops-the-number", MAN,
     'out.append(f"\\n[{st.name} #{n}]  {src}".rstrip())',
     'out.append(f"\\n[{st.name} #1]  {src}".rstrip())', T_MAN),
    ("manual-template-omits-the-japanese", MAN,
     'src = " ".join(str(r.get("src_text") or "").split())',
     'src = ""', T_MAN),
    ("manual-template-omits-what-is-translated", MAN,
     'out.append(dst if dst else "")',
     'out.append("")', T_MAN),
    ("manual-pages-argument-ignored", MAN,
     "out = [HEAD]\n"
     "    for i in (range(len(p.pages)) if idxs is None else idxs):",
     "out = [HEAD]\n    for i in range(len(p.pages)):", T_MAN),
    ("manual-boxes-unordered", MAN,
     'recs = sorted(st.regions, key=lambda r: r.get("order", 0))',
     'recs = list(st.regions)', T_MAN),

    # ---- the file that comes back
    ("manual-comments-are-read-as-dialogue", MAN,
     'if raw.lstrip().startswith("#"):\n            continue',
     'if False:\n            continue', T_MAN),
    ("manual-empty-block-still-overwrites", MAN,
     "if body.strip():\n            out.append((cur[0], cur[1], body.strip()))",
     "out.append((cur[0], cur[1], body.strip()))", T_MAN),
    ("manual-second-line-dropped", MAN,
     "if cur is not None:\n            buf.append(raw.rstrip())",
     "if cur is not None and not buf:\n            buf.append(raw.rstrip())",
     T_MAN),
    ("manual-json-not-tried", MAN,
     'if t[:1] in "[{":', "if False:", T_MAN),

    # ---- overriding
    ("import-fills-only-the-empty-ones", PY,
     "        set_translation(rec, eng)\n        n_regions += 1",
     "        if not (rec.get('dst_text') or '').strip():\n"
     "            set_translation(rec, eng)\n        n_regions += 1", T_MAN),
    ("set-keeps-the-old-layout", PY,
     '\n    rec["layout"] = ({"lines": [], "frame": keep,',
     '\n    rec["layout"] = rec.get("layout") or ({"lines": [], "frame": keep,',
     T_MAN),
    ("set-keeps-the-proofread-tick", PY,
     '    rec.pop("proofread", None)              # new text',
     '    rec.get("proofread")                    # new text', T_MAN),
    ("set-keeps-the-old-hand-typed-lines", PY,
     '        for k in ("lines", "fit", "wrap", "snug"):\n'
     '            ov.pop(k, None)',
     '        for k in ():\n            ov.pop(k, None)', T_MAN),
    ("set-throws-the-styling-away-too", PY,
     '        for k in ("lines", "fit", "wrap", "snug"):\n'
     '            ov.pop(k, None)',
     '        for k in list(ov):\n            ov.pop(k, None)', T_MAN),
    ("set-loses-a-text-box-frame", PY,
     '    if rec.get("own_text"):\n'
     '        keep = list((rec.get("layout") or {}).get("frame") or []) or None',
     '    if False:\n'
     '        keep = list((rec.get("layout") or {}).get("frame") or []) or None',
     T_MAN),
    ("set-does-not-normalise", PY,
     '    rec["dst_text"] = typeset_mod.normalize_text(str(text or "").strip())',
     '    rec["dst_text"] = str(text or "").strip()', T_MAN),
    ("import-swallows-a-label-that-matches-nothing", PY,
     '            missing.append(f"{name} #{n}: page has no box {n}")',
     '            pass', T_MAN),
    ("import-does-not-save", PY, "    p.save()\n    _page_cache.clear()",
     "    _page_cache.clear()", T_MAN),

    # ---- the mode on screen
    ("greys-nothing", JS,
     "const MANUAL_GREY=[1,2,3];", "const MANUAL_GREY=[];", T_MAN),
    ("greys-everything", JS,
     "const MANUAL_GREY=[1,2,3];", "const MANUAL_GREY=[0,1,2,3,4,5,6];", T_MAN),
    ("greys-the-wrong-three", JS,
     "const MANUAL_GREY=[1,2,3];", "const MANUAL_GREY=[4,5,6];", T_MAN),
    ("grey-still-runs", JS,
     "  if(manualOff(i)) return;       // translating it yourself",
     "  if(false) return;              // translating it yourself", T_MAN),
    ("grey-class-never-applied", JS,
     "    if(manualOff(i)) cls += ' off';", "    if(false) cls += ' off';",
     T_MAN),
    ("mode-ignores-the-setting", JS,
     "  return !!(typeof proj!=='undefined' && proj && proj.settings\n"
     "            && proj.settings.manual_translate);",
     "  return false;", T_MAN),
    ("template-row-always-shown", JS,
     "  const r=$('manrow'); if(r) r.style.display = on ? '' : 'none';",
     "  const r=$('manrow'); if(r) r.style.display = '';", T_MAN),
    ("sync-does-not-redraw-the-bar", JS,
     "  if(typeof renderSteps==='function' && $('steps'))\n"
     "    renderSteps((proj&&proj.job&&proj.job.running)?proj.job.label:null);",
     "  ;", T_MAN),

    # ---- the substitutes round, re-measured
    ("substitutes-on-in-the-library-default", "mangatl/typeset.py",
     "\n    substitutes: bool = False\n",
     "\n    substitutes: bool = True\n", T_FONT),
    ("settings-default-substitutes-off", "mangatl/project.py",
     '"substitutes": True,', '"substitutes": False,', T_FONT),

    # ---- the courtesy re-typeset after new words arrive
    ("import-re-typesets-with-the-reset", PY,
     '        run_job(p, "Laying out text", sorted(touched),\n'
     '                lambda i: do_typeset(p, i, reset=False))',
     '        run_job(p, "Laying out text", sorted(touched),\n'
     '                lambda i: do_typeset(p, i))', T_MAN),
    ("restore-never-puts-them-back", PY,
     "        if reset or not own:\n            return",
     "        if True:\n            return", T_MAN),
    ("restore-skipped-when-there-is-nothing-to-typeset", PY,
     "        return restore()", "        return", T_MAN),
    ("restore-skipped-after-laying-out", PY,
     "    _commit_keep_proofread(p, i, page)\n    restore()",
     "    _commit_keep_proofread(p, i, page)", T_MAN),
    ("reset-is-ignored-and-nothing-is-ever-swept-up", PY,
     "    own = [r for r in p.pages[i].regions if r.get(\"own_text\")]\n"
     "    if own:",
     "    own = [r for r in p.pages[i].regions if r.get(\"own_text\")]\n"
     "    reset = False\n    if own:", T_MAN),
    ("sanitise-substitutes-always", "mangatl/typeset.py",
     "    cov = _font_coverage(font_path) if font_path and substitutes else None",
     "    cov = _font_coverage(font_path) if font_path else None", T_FONT),
    ("no-flag-when-a-glyph-is-missing", "mangatl/typeset.py",
     '        if missing:\n            region.flagged = ',
     '        if False:\n            region.flagged = ', T_FONT),
    ("cfg-ignores-the-setting", PY,
     'substitutes=bool(s.get("substitutes"))', "substitutes=True", T_FONT),

    # ---- outside text and sfx running past the box (2026-08-04)
    ("spill-never-happens", "mangatl/typeset.py",
     '    if _kinds.family_of(region.kind) == "freefloat":\n'
     '        lay = _spill_fit(text, m, cfg)',
     '    if False:\n        lay = _spill_fit(text, m, cfg)', T_SPILL),
    ("spill-for-bubbles-too", "mangatl/typeset.py",
     '    if _kinds.family_of(region.kind) == "freefloat":',
     '    if True:', T_SPILL),
    ("spill-below-the-minimum", "mangatl/typeset.py",
     "    path, size = cfg.font_path, cfg.min_font",
     "    path, size = cfg.font_path, cfg.absolute_floor", T_SPILL),
    ("spill-not-marked", "mangatl/typeset.py",
     "                      fit_ok=True, spills=True)",
     "                      fit_ok=True, spills=False)", T_SPILL),
    ("spill-hung-off-the-corner", "mangatl/typeset.py",
     "    cx, cy = bx + bw / 2.0, by + bh / 2.0\n"
     "    top = cy - len(lines) * lh / 2.0",
     "    cx, cy = bx, by\n    top = cy - len(lines) * lh / 2.0", T_SPILL),
    ("sfx-sweep-goes-under-the-minimum", "mangatl/typeset.py",
     "    lay = fit_sfx(frame, text, measure, lo=cfg.min_font, hi=160)",
     "    lay = fit_sfx(frame, text, measure, lo=cfg.absolute_floor, hi=160)",
     T_SPILL),
    ("clamp-shrinks-past-the-minimum", "mangatl/typeset.py",
     "    floor = cfg.min_font\n    want = int(lay.font_size * scale)",
     "    floor = cfg.absolute_floor\n    want = int(lay.font_size * scale)",
     T_SPILL),
    ("clamp-grows-a-tiny-effect", "mangatl/typeset.py",
     "    if size >= lay.font_size:\n        return lay",
     "    if False:\n        return lay", T_SPILL),
    ("spilling-block-is-clamped-into-its-region", "mangatl/typeset.py",
     '    if getattr(lay, "spills", False):\n        return lay',
     "    if False:\n        return lay", T_SPILL),
    ("render-clips-the-spill-back-to-the-box", "mangatl/render.py",
     "        free = free or bool(getattr(lay, \"spills\", False))",
     "        free = free or False", T_SPILL),
    ("render-clips-nothing-at-all", "mangatl/render.py",
     "        free = free or bool(getattr(lay, \"spills\", False))",
     "        free = True", T_SPILL),
    ("spill-runs-off-the-page", "mangatl/typeset.py",
     "            if r.layout and getattr(r.layout, \"spills\", False):\n"
     "                r.layout = keep_on_page(r.layout, cfg, page.image.shape)",
     "            if False:\n"
     "                r.layout = keep_on_page(r.layout, cfg, page.image.shape)",
     T_SPILL),
    ("keep-on-page-runs-before-the-frame-is-settled", "mangatl/typeset.py",
     "                r.layout = anchor_to_frame(r.layout, cfg)\n"
     "            # Out of the box is allowed; off the page is not. AFTER",
     "                pass\n"
     "            # Out of the box is allowed; off the page is not. AFTER",
     T_SPILL),
    ("keep-on-page-shoves-a-block-wider-than-the-page", "mangatl/typeset.py",
     "    if right - left <= W:\n        dx = ", "    if True:\n        dx = ",
     T_SPILL),

    # ---- the healing brush lee threw out
    ("heal-falls-back-to-the-local-fill", PY,
     "                if neural is None:\n"
     "                    return self._json({\"error\": clean_warning(p) or (",
     "                if False:\n"
     "                    return self._json({\"error\": clean_warning(p) or (",
     T_HEAL),
    ("heal-answers-when-the-model-fails", PY,
     "                if out is None or out.shape != img.shape:\n"
     "                    return self._json({\"error\": clean_warning(p) or (",
     "                if False:\n"
     "                    return self._json({\"error\": clean_warning(p) or (",
     T_HEAL),
    ("heal-not-strict", PY,
     "neural, _all = _make_cleaner(p, strict=True)",
     "neural, _all = _make_cleaner(p, strict=False)", T_HEAL),
    ("two-brushes-back-on-the-toolbar", "mangatl/static/js/toolbar.js",
     "    {k:'heal',   name:'Healing brush', icon:'healai',",
     "    {k:'healai', name:'AI healing brush', icon:'healai',", T_HEAL),

    # ---- the webtoon strip, put back together (strip.py)
    ("strip-any-row-is-flat-enough", STR,
     "FLAT_STD = 4.0",
     "FLAT_STD = 40.0", T_STRIP),
    ("strip-flatness-on-the-spread-alone", STR,
     "    return (r[:, 2] < FLAT_STD) & ((r[:, 1] - r[:, 0]) < FLAT_RANGE)",
     "    return (r[:, 2] < FLAT_STD)", T_STRIP),
    ("strip-one-flat-row-is-a-gutter", STR,
     "def gutters(flat: np.ndarray, min_band: int = MIN_GUTTER) -> list[int]:",
     "def gutters(flat: np.ndarray, min_band: int = 1) -> list[int]:", T_STRIP),
    ("strip-cut-at-the-top-of-the-gutter", STR,
     "    return [int((a + b) // 2) for a, b in zip(starts, ends) if b - a >= min_band]",
     "    return [int(a) for a, b in zip(starts, ends) if b - a >= min_band]",
     T_STRIP),
    ("strip-quietest-takes-the-first-gap-not-the-longest", STR,
     "    k = int(np.argmax(b - a))",
     "    k = 0", T_STRIP),
    ("strip-first-gutter-past-the-target", STR,
     "            cuts.append(int(near[np.argmin(abs(near - (at + target)))]))",
     "            cuts.append(int(near[np.argmax(near >= at + target)]))",
     T_STRIP),
    ("strip-first-gutter-in-the-window", STR,
     "            cuts.append(int(near[np.argmin(abs(near - (at + target)))]))",
     "            cuts.append(int(near[0]))", T_STRIP),
    ("strip-runs-on-past-the-ceiling", STR,
     "        if len(after) and after[0] - at <= ceiling:",
     "        if len(after):", T_STRIP),
    ("strip-forced-cut-not-reported", STR,
     "        cuts.append(int(cut))\n        forced.append(int(cut))",
     "        cuts.append(int(cut))\n        forced = forced", T_STRIP),
    ("strip-a-handful-of-files-is-a-strip", STR,
     "    if len(sizes) < 6:",
     "    if len(sizes) < 2:", T_STRIP),
    ("strip-widths-need-not-match", STR,
     "    if len(ws) != 1:\n        return False",
     "    if False:\n        return False", T_STRIP),
    ("strip-heights-need-not-match", STR,
     "    if len(set(hs[:-1])) != 1:\n        return False",
     "    if False:\n        return False", T_STRIP),
    ("strip-the-last-tile-may-be-the-tallest", STR,
     "    if hs[-1] > hs[0]:\n        return False",
     "    if False:\n        return False", T_STRIP),
    ("strip-a-landscape-scan-is-a-webtoon", STR,
     "    return hs[0] > sizes[0][1] * 1.2",
     "    return True", T_STRIP),

    # ---- and how the project uses it
    ("strip-never-runs-on-upload", PY,
     "                report = p.restitch_if_sliced()",
     "                report = {}", T_STRIP),
    ("strip-report-never-reaches-the-browser", PY,
     '                                   "strip": report or None})',
     '                                   "strip": None})', T_STRIP),
    ("strip-the-switch-is-ignored", PRJ,
     '        if not force and not self.settings.get("restitch_strips", True):',
     "        if False:", T_STRIP),
    ("strip-re-cuts-a-chapter-already-worked-on", PRJ,
     "        if any(pg.detected or pg.regions or pg.typeset or pg.cleaned\n"
     "               for pg in self.pages):",
     "        if False:", T_STRIP),
    ("strip-page-height-setting-ignored", PRJ,
     '        target = int(self.settings.get("strip_target") or _strip.TARGET_H)',
     "        target = _strip.TARGET_H", T_STRIP),
    ("strip-ceiling-setting-ignored", PRJ,
     '        ceiling = int(self.settings.get("strip_max") or _strip.MAX_H)',
     "        ceiling = _strip.MAX_H", T_STRIP),
    ("strip-writes-into-somebody-elses-folder", PRJ,
     '        own = os.path.abspath(self.input_dir or "") == os.path.abspath(',
     '        own = True or os.path.abspath(self.input_dir or "") == os.path.abspath(',
     T_STRIP),
    ("strip-a-one-page-chapter-is-accepted", PRJ,
     '        if len(rep.get("pages") or []) < 2:',
     '        if len(rep.get("pages") or []) < 0:', T_STRIP),
    ("strip-pages-sorted-alphabetically", PRJ,
     "    return sorted(set(out), key=natural_key)",
     "    return sorted(set(out))", T_STRIP),
    ("strip-order-has-no-last-word", PRJ,
     "    return key + [(0, 0, path)]",
     "    return key", T_STRIP),

    # ---- the dialog wears our own mark
    ("mark-dialog-keeps-tks-feather", PICK,
     "    _wear_our_own_icon(root)\n",
     "", T_MARK),
    ("mark-lost-in-white-space", ICON,
     "FILL = 0.94", "FILL = 0.35", T_MARK),
    ("mark-is-a-square", ICON,
     "    ImageDraw.Draw(shape).polygon(\n"
     "        [(x * scale + ox, y * scale + oy) for x, y in PATH], fill=255)",
     "    ImageDraw.Draw(shape).rectangle([0, 0, big, big], fill=255)", T_MARK),
    ("mark-one-size-only", ICON,
     "ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)",
     "ICO_SIZES = (256,)", T_MARK),

    # ---- narrower before the artwork, and never off the page
    ("page-only-spilling-blocks-are-kept-on", TS,
     "            if r.layout:\n"
     "                r.layout = keep_on_page(r.layout, cfg, page.image.shape)",
     '            if r.layout and getattr(r.layout, "spills", False):\n'
     "                r.layout = keep_on_page(r.layout, cfg, page.image.shape)",
     T_SPILL),
    ("page-a-turned-line-is-measured-level", TS,
     '    rot = math.radians(float(getattr(lay, "rotate", 0.0) or 0.0))',
     "    rot = 0.0", T_SPILL),
    ("narrow-jumps-the-spills-queue", TS,
     "    if _kinds.family_of(region.kind) == \"freefloat\":\n"
     "        lay = _spill_fit(text, m, cfg)\n        if lay is not None:\n"
     "            return lay",
     "    if False:\n        lay = _spill_fit(text, m, cfg)\n"
     "        if lay is not None:\n            return lay", T_SPILL),
    ("narrow-never-tried", TS,
     "    lay = _narrower_fit(text, m, cfg)\n    if lay is not None:\n"
     "        return lay",
     "    lay = None\n    if lay is not None:\n        return lay", T_SPILL),
    ("narrow-cap-not-actually-lifted", TS,
     "    return _best(text, mask, replace(cfg, max_lines=DESPERATE_LINES))",
     "    return _best(text, mask, cfg)", T_SPILL),
    ("narrow-runs-on-balloons-that-were-fine", TS,
     "    lay = _fit_on_author_breaks(text, m, cfg)\n    if lay is not None:\n"
     "        return lay\n\n    # Still nothing.",
     "    lay = None\n    if lay is not None:\n        return lay\n\n"
     "    # Still nothing.",
     T_SPILL + ["tests/test_breaking_at_the_authors_dashes.py"]),

    # ---- a chapter in one file
    ("tctp-paths-stay-absolute", BUN,
     '    out["input_dir"] = "input"',
     '    out["input_dir"] = root', T_TCTP),
    ("tctp-page-paths-stay-absolute", BUN,
     "        for field, folder in PAGE_FILES:\n"
     "            if pg.get(field):\n"
     "                pg[field] = _rel(str(pg[field]), root, folder)",
     "        for field, folder in PAGE_FILES:\n"
     "            if False:\n"
     "                pg[field] = _rel(str(pg[field]), root, folder)", T_TCTP),
    ("tctp-fonts-not-carried", BUN,
     "        for name, real in sorted(faces.items()):\n"
     "            z.write(real, posixpath.join(FONTS, name))",
     "        for name, real in sorted(faces.items()):\n            pass",
     T_TCTP),
    ("tctp-a-box-may-keep-its-own-face", BUN,
     '            for key in ("layout", "layout_override"):',
     "            for key in ():", T_TCTP),
    ("tctp-custom-box-types-lose-their-face", BUN,
     '    if isinstance(s.get("custom_kinds"), list):',
     "    if False:", T_TCTP),
    ("tctp-a-face-here-is-overwritten", BUN,
     "                if fh.read() == data:\n                    return dest",
     "                if True:\n                    return dest", T_TCTP),
    ("tctp-the-caches-are-carried-too", BUN,
     'CARRIED = ("input", "paint", "custom_clean")',
     'CARRIED = ("input", "paint", "custom_clean", "plate_cache",\n'
     '           "ai_clean_cache")', T_TCTP),
    ("tctp-anything-zip-shaped-is-a-project", BUN,
     "            if MANIFEST not in names or STATE not in names:\n"
     "                return False",
     "            if False:\n                return False", T_TCTP),
    ("tctp-checked-after-the-deleting", BUN,
     '    if not looks_like_bundle(data):\n'
     '        raise ValueError("that file is not a MangaTCT project")',
     "    pass", T_TCTP),
    ("tctp-a-zip-may-walk-upwards", BUN,
     '             if q not in ("", ".", "..") and ":" not in q]',
     '             if q not in ("", ".") and ":" not in q]', T_TCTP),
    ("tctp-a-zip-may-walk-sideways-onto-another-drive", BUN,
     '             if q not in ("", ".", "..") and ":" not in q]',
     '             if q not in ("", ".", "..")]', T_TCTP),
    ("tctp-save-forgets-where", PY,
     '                p.settings["project_file"] = dest',
     "                pass", T_TCTP),
    ("tctp-save-without-the-extension", PY,
     "                if not dest.lower().endswith(bundle.EXT):\n"
     "                    dest += bundle.EXT",
     "                if False:\n                    dest += bundle.EXT", T_TCTP),
    ("tctp-import-left-under-settings", HTML,
     '''            onclick="$('impSet').click()">Import story context&hellip;</button>\n''',
     '', T_TCTP),
    ("tctp-the-input-stayed-behind", HTML,
     '     <input id="impSet" type="file" accept=".tct,.json,application/json"',
     '     <input id="impSetGone" type="file" accept=".tct,.json,application/json"',
     T_TCTP),
    ("tctp-download-named-input", PY,
     '    if stem.lower() in ("", "input", "strip"):',
     "    if False:", T_TCTP),

    # ---- a spill still takes the author's breaks first
    ("spill-wraps-on-spaces-only", TS,
     "    toks, glue = author_break_tokens(text)\n    lines, cur = [], \"\"\n"
     "    for k, tk in enumerate(toks):",
     "    toks, glue = text.split(), [False] * len(text.split())\n"
     "    lines, cur = [], \"\"\n    for k, tk in enumerate(toks):", T_SPILL),
    ("spill-puts-a-space-back-in-the-word", TS,
     "        trial = tk if not cur else (cur + tk if glue[k] else cur + \" \" + tk)",
     "        trial = tk if not cur else cur + \" \" + tk", T_SPILL),
    ("spill-breaks-every-piece-onto-its-own-line", TS,
     "        trial = tk if not cur else (cur + tk if glue[k] else cur + \" \" + tk)\n"
     "        if _text_w(path, size, trial) <= avail_w or not cur:",
     "        trial = tk if not cur else (cur + tk if glue[k] else cur + \" \" + tk)\n"
     "        if not cur:", T_SPILL),

    # ---- no pause the page never drew
    ("dots-leading-ellipsis-kept", TR,
     "    if not (dst or \"\").strip() or source_leads_with_ellipsis(src):\n"
     "        return dst",
     "    if True:\n        return dst", T_DOTS),
    ("dots-source-never-earns-one", TR,
     "    return bool(_LEADS.match(src or \"\"))",
     "    return False", T_DOTS),
    ("dots-a-single-period-is-an-ellipsis", TR,
     '_ELLIPSIS = r"(?=[…‥]|[.．・]{2})[.．・…‥]+"',
     '_ELLIPSIS = r"[.．・…‥]+"', T_DOTS),
    ("dots-brackets-hide-it", TR,
     '_OPENERS = r"[\\"\'“”‘’«»「」『』（）()\\[\\]【】\\s]*"',
     '_OPENERS = r""', T_DOTS),
    ("dots-a-bare-ellipsis-line-is-emptied", TR,
     "    t = _LEADS.sub(r\"\\1\", dst, count=1)\n    return t.strip() or dst",
     "    t = _LEADS.sub(r\"\\1\", dst, count=1)\n    return t.strip()", T_DOTS),
    ("dots-the-trailing-half-goes-too", TR,
     '_LEADS = re.compile(rf"^({_OPENERS}){_ELLIPSIS}\\s*")',
     '_LEADS = re.compile(rf"({_OPENERS}){_ELLIPSIS}\\s*")', T_DOTS),
    ("dots-translator-door-shut", TR,
     "                r.dst_text = strip_added_ellipsis(\n"
     "                    strip_added_dashes(fixed, r.src_text), r.src_text)",
     "                r.dst_text = strip_added_dashes(fixed, r.src_text)", T_DOTS),
    ("dots-proofreader-door-shut", TR,
     "            r.dst_text = strip_added_ellipsis(\n"
     "                strip_added_dashes(\n"
     "                    normalize_text(str(item.get(\"translation\") or \"\").strip()),\n"
     "                    r.src_text),\n                r.src_text)",
     "            r.dst_text = strip_added_dashes(\n"
     "                normalize_text(str(item.get(\"translation\") or \"\").strip()),\n"
     "                r.src_text)", T_DOTS),
    ("dots-import-door-shut", PY,
     "    rec[\"dst_text\"] = strip_added_ellipsis(\n"
     "        typeset_mod.normalize_text(str(text or \"\").strip()),\n"
     "        str(rec.get(\"src_text\") or \"\"))",
     "    rec[\"dst_text\"] = typeset_mod.normalize_text(str(text or \"\").strip())",
     T_DOTS),
    ("dots-prompt-still-asks-for-it", TR,
     "- Never START a line with an ellipsis the {source} does not start with. The",
     "- Sometimes START a line with an ellipsis. The", T_DOTS),

    # ---- which box the words are in
    ("box-outline-is-the-bounding-rectangle-again", OCR,
     "    (cx, cy), (rw, rh), ang = cv2.minAreaRect(pts)",
     "    (cx, cy), (rw, rh), ang = (pts.mean(0).tolist(),\n"
     "        (float(pts[:, 0].ptp()), float(pts[:, 1].ptp())), 0.0)", T_BOX),
    ("box-outline-ignores-who-owns-the-ink", OCR,
     "    if owner is not None and index >= 0:\n"
     "        sub = sub & (owner[y0:y1, x0:x1] == index)",
     "    if False:\n"
     "        sub = sub & (owner[y0:y1, x0:x1] == index)", T_BOX),
    ("box-outline-reads-the-whole-page", OCR,
     "    x0, y0 = max(0, x - PAD), max(0, y - PAD)\n"
     "    x1, y1 = min(W, x + w + PAD), min(H, y + h + PAD)\n"
     "    if x1 <= x0 or y1 <= y0:\n        return None",
     "    x0, y0 = 0, 0\n    x1, y1 = W, H\n"
     "    if x1 <= x0 or y1 <= y0:\n        return None", T_BOX),
    ("box-outline-drawn-right-on-the-glyphs", OCR,
     "    return cv2.boxPoints(((cx, cy), (rw + GROW * 2, rh + GROW * 2), ang)\n"
     "                         ).astype(np.int32)",
     "    return cv2.boxPoints(((cx, cy), (rw, rh), ang)).astype(np.int32)",
     T_BOX),
    ("box-reader-not-told-the-closer-fit-wins", "mangatl/translate.py",
     '        "one outline, it belongs to the outline that fits it most closely, not "',
     '        "one outline, it belongs to whichever you like, not "', T_BOX),
    ("box-a-speck-is-a-shape", OCR,
     "    if len(xs) < MIN_INK:", "    if len(xs) < 1:", T_BOX),
    ("box-no-mask-is-an-empty-shape", OCR,
     "    m = getattr(region, \"text_mask\", None)\n    if m is None:\n"
     "        return None",
     "    m = getattr(region, \"text_mask\", None)\n    if False:\n"
     "        return None", T_BOX),
    ("box-outline-never-reaches-the-reader", OCR,
     "            cv2.polylines(vis, [_shape(r, x0, y0, shapes.get(r.id))], True,",
     "            cv2.polylines(vis, [_shape(r, x0, y0, None)], True,", T_BOX),
    ("box-shapes-computed-without-the-owner-map", OCR,
     "    shapes = {r.id: ink_outline(r, owner, index_of.get(r.id, -1))\n"
     "              for r in regions}",
     "    shapes = {r.id: ink_outline(r) for r in regions}", T_BOX),
    ("box-lines-painted-over-the-words", OCR,
     "        keep = owner[y0:y1, x0:x1] >= 0\n"
     "        if keep.any():\n"
     "            vis[keep] = img[y0:y1, x0:x1][keep]",
     "        keep = owner[y0:y1, x0:x1] >= 0\n"
     "        if False:\n"
     "            vis[keep] = img[y0:y1, x0:x1][keep]", T_BOX),
    ("box-the-words-rub-out-the-lines", OCR,
     "        keep = owner[y0:y1, x0:x1] >= 0",
     "        keep = owner[y0:y1, x0:x1] > -99", T_BOX),
    ("box-numbers-painted-out-by-the-restore", OCR,
     "        for r in here:\n"
     "            if r.id in ids:\n"
     "                _draw_tag(vis, r, _shape(r, x0, y0, shapes.get(r.id)))",
     "        pass", T_BOX),
    ("box-a-neighbour-is-drawn-red-too", OCR,
     "                          (0, 0, 255) if r.id in ids else (168, 168, 168), 2)",
     "                          (0, 0, 255), 2)", T_BOX),
    ("box-number-goes-back-on-the-top-left-corner", OCR,
     "    tx, ty = _tag_spot(vis, pts, bw, bh)",
     "    tx, ty = int(pts[:, 0].min()), max(0, int(pts[:, 1].min()) - bh)",
     T_BOX),
    ("box-reader-not-told-about-slanted-outlines", "mangatl/translate.py",
     '        "An outline follows the SHAPE of the words it holds, so a line of text "',
     '        "" or (', T_BOX),
    ("box-number-ignores-the-ink-under-it", OCR,
     "        s = (float(255 - patch.mean()) if patch.size else 1e9, ay)",
     "        s = (0.0, ay)", T_BOX),

    # ---- a run that fell over kept its pages
    ("save-only-at-the-end-of-the-run", PY,
     "            p.save_soon()\n    except Exception as e:",
     "            pass\n    except Exception as e:", T_KEPT),
    ("save-skipped-when-the-run-raises", PY,
     "        try:\n            p.save()\n        except Exception:\n"
     "            traceback.print_exc()\n        p.job[\"running\"] = False",
     "        try:\n            if not p.job.get(\"error\"):\n"
     "                p.save()\n        except Exception:\n"
     "            traceback.print_exc()\n        p.job[\"running\"] = False",
     T_KEPT),
    ("save-swallowed-by-its-own-guard", PY,
     "        try:\n            p.save()\n        except Exception:\n"
     "            traceback.print_exc()",
     "        try:\n            pass\n        except Exception:\n"
     "            traceback.print_exc()", T_KEPT),
    ("save-per-page-costs-a-write-each-time", PY,
     "            p.save_soon()\n    except Exception as e:",
     "            p.save()\n    except Exception as e:", T_KEPT),

    # ---- TCT Coins
    ("coin-a-dollar-is-ten-coins", COIN,
     "COINS_PER_DOLLAR = 100", "COINS_PER_DOLLAR = 10", T_COIN),
    ("coin-nothing-is-doubled", COIN, "MARKUP = 2", "MARKUP = 1", T_COIN),
    ("coin-doubled-twice", COIN, "MARKUP = 2", "MARKUP = 4", T_COIN),
    ("coin-a-fraction-rounds-down-to-free", COIN,
     "    return int(math.ceil(max(0.0, float(usd)) * COINS_PER_DOLLAR * MARKUP))",
     "    return int(max(0.0, float(usd)) * COINS_PER_DOLLAR * MARKUP)", T_COIN),
    ("coin-show-invents-a-fraction", COIN,
     '    return str(int(coins))', '    return "%.2f" % coins', T_COIN),
    ("coin-the-chapter-context-is-not-counted", COIN,
     "           + sh.chapter_in * max(0, int(chapter_boxes or 0))\n",
     "", T_COIN),
    # The bug this replaced: `max(boxes, chapter_boxes)` meant an explicit
    # nought was read as "well, this page's worth", and a full-chapter run —
    # which sends NO context — was quoted a hundred thousand tokens it never
    # sent.
    ("coin-the-chapter-context-is-only-this-page", COIN,
     "           + sh.chapter_in * max(0, int(chapter_boxes or 0))",
     "           + sh.chapter_in * max(boxes, int(chapter_boxes or 0))", T_COIN),
    ("coin-a-scoped-run-forgets-the-chapter", PY,
     "    ctx = context_boxes(p, step, indices)\n"
     "    return (coins.quote(step, [page_boxes(p, i) for i in indices],\n"
     "                        model, backend, ctx), model, backend)",
     "    return (coins.quote(step, [page_boxes(p, i) for i in indices],\n"
     "                        model, backend), model, backend)", T_COIN),
    ("coin-the-refund-is-priced-on-a-different-sum", PY,
     "                back = coins.quote(step, boxes[done:], model, backend, ctx)",
     "                back = coins.quote(step, boxes[done:], model, backend)",
     T_COIN),
    ("coin-googles-cache-is-assumed", COIN,
     "            if vendor_free(model).startswith(MARKS_CACHE) else 0)",
     "            if True else 0)", T_COIN),
    ("coin-nothing-is-ever-cached", COIN,
     "            if vendor_free(model).startswith(MARKS_CACHE) else 0)",
     "            if False else 0)", T_COIN),
    # The shape this replaced: one per-box output number with the reasoning
    # smeared across it, so a two-box page was quoted as thinking a fifth as
    # hard as a ten-box page and Claude was quoted for thinking it never did.
    ("coin-the-reasoning-is-smeared-across-the-boxes", COIN,
     "                       per_box_out=28, think_out=1689),",
     "                       per_box_out=142, think_out=0),", T_COIN),

    ("coin-nobody-is-charged-for-thinking", COIN,
     "                       per_box_out=28, think_out=1689),",
     "                       per_box_out=28, think_out=0),", T_COIN),
    ("coin-price-ignores-the-boxes", COIN,
     "    tin = (sh.fixed_in + sh.per_box_in * boxes",
     "    tin = (sh.fixed_in + sh.per_box_in * 9", T_COIN),
    ("coin-reply-is-free", COIN,
     "    tout = sh.fixed_out + sh.per_box_out * boxes\n",
     "    tout = 0\n", T_COIN),
    ("coin-an-empty-page-is-charged-anyway", COIN,
     "    if sh is None or boxes <= 0:\n        return 0.0",
     "    if sh is None:\n        return 0.0", T_COIN),
    ("coin-a-run-is-rounded-up-page-by-page", COIN,
     "    return coins_for_usd(sum(usd_page(step, n, model, backend, whole)\n"
     "                             for n in counts))",
     "    return sum(coins_for_usd(usd_page(step, n, model, backend, whole))\n"
     "               for n in counts)", T_COIN),
    ("coin-a-run-is-rounded-down", COIN,
     "    return coins_for_usd(sum(usd_page(step, n, model, backend, whole)\n"
     "                             for n in counts))",
     "    return int(sum(usd_page(step, n, model, backend, whole)\n"
     "                   for n in counts) * COINS_PER_DOLLAR * MARKUP)", T_COIN),
    ("coin-cleaning-is-per-box-after-all", COIN,
     '    if step == "clean":\n        return CLEAN_USD_PER_PAGE',
     '    if step == "clean":\n        return CLEAN_USD_PER_PAGE * max(1, boxes)',
     T_COIN),
    ("coin-a-free-step-is-charged", COIN,
     "    sh = SHAPES.get(step)\n    if sh is None or boxes <= 0:",
     "    sh = SHAPES.get(step) or SHAPES[\"translate\"]\n"
     "    if sh is None or boxes <= 0:", T_COIN),
    ("coin-your-own-machine-is-billed", COIN,
     '    if (backend or "").strip().lower() in FREE_BACKENDS:\n'
     "        return Rate(0.0, 0.0)",
     "    if False:\n        return Rate(0.0, 0.0)", T_COIN),
    ("coin-shortest-prefix-wins", COIN,
     "        if m.startswith(key) and len(key) > len(hit):",
     "        if m.startswith(key) and not hit:", T_COIN),
    ("coin-an-unknown-model-is-free", COIN,
     "UNKNOWN = _anthropic(15.0, 75.0)", "UNKNOWN = Rate(0.0, 0.0)", T_COIN),
    ("coin-an-unknown-model-is-mid-range", COIN,
     "UNKNOWN = _anthropic(15.0, 75.0)", "UNKNOWN = _anthropic(1.0, 5.0)",
     T_COIN),
    ("coin-sonnet-on-the-promotional-rate", COIN,
     '    "claude-sonnet-5": _anthropic(3.0, 15.0),',
     '    "claude-sonnet-5": _anthropic(2.0, 10.0),', T_COIN),
    ("coin-lite-priced-as-its-full-size-sibling", COIN,
     '    "gemini-3.5-flash-lite": _google(0.30, 2.50),\n'
     '    "gemini-3.5-flash": _google(1.50, 9.00),',
     '    "gemini-3.5-flash": _google(1.50, 9.00),', T_COIN),
    ("coin-a-dated-snapshot-falls-through", COIN,
     "    return _prefix(m) or _prefix(vendor_free(m)) or UNKNOWN",
     "    return RATES.get(m) or UNKNOWN", T_COIN),
    ("coin-googles-cache-costs-to-write", COIN,
     "    return Rate(inp, out, round(inp * 0.10, 4), 0.0)",
     "    return Rate(inp, out, round(inp * 0.10, 4), round(inp * 1.25, 4))",
     T_COIN),
    ("coin-the-cache-is-not-a-discount", COIN,
     "    return Rate(inp, out, round(inp * 0.10, 4), round(inp * 1.25, 4))\n"
     "\n\ndef _google",
     "    return Rate(inp, out, inp, round(inp * 1.25, 4))\n\n\ndef _google",
     T_COIN),
    ("coin-the-cache-is-billed-at-full-price", COIN,
     "        cr = self.cache_read if self.cache_read else self.inp",
     "        cr = self.inp", T_COIN),
    ("coin-a-new-purse-opens-empty", COIN,
     "WELCOME = 1000", "WELCOME = 0", T_COIN),
    ("coin-the-purse-is-never-written", COIN,
     '        _entry(w, kind="spend", what=what or "ai", page=page, model=model,\n'
     "               coins=coins, **extra)\n        _write(w)",
     '        _entry(w, kind="spend", what=what or "ai", page=page, model=model,\n'
     "               coins=coins, **extra)", T_COIN),
    ("coin-a-credit-is-taken-out", COIN,
     '        w["balance"] = int(w.get("balance") or 0) + coins\n'
     '        _entry(w, kind="credit", what=what, coins=coins)',
     '        w["balance"] = int(w.get("balance") or 0) - coins\n'
     '        _entry(w, kind="credit", what=what, coins=coins)', T_COIN),
    ("coin-a-negative-credit-empties-it", COIN,
     "    if coins <= 0:\n        return balance()",
     "    if False:\n        return balance()", T_COIN),
    ("coin-the-ledger-grows-for-ever", COIN,
     "    del w[\"ledger\"][:-LEDGER_MAX]", "    pass", T_COIN),
    ("coin-a-broken-wallet-file-raises", COIN,
     "    except Exception:\n        pass\n"
     '    return {"balance": WELCOME, "ledger": [',
     "    except Exception:\n        raise\n"
     '    return {"balance": WELCOME, "ledger": [', T_COIN),
    ("coin-the-screen-is-told-about-dollars", COIN,
     '        return {"balance": int(_read().get("balance") or 0), "buy_url": BUY_URL}',
     '        return {"balance": int(_read().get("balance") or 0),\n'
     '                "buy_url": BUY_URL, "per_dollar": COINS_PER_DOLLAR}', T_COIN),
    ("coin-nowhere-to-buy-them", COIN,
     'BUY_URL = "https://mangatct.com/coins"', 'BUY_URL = ""', T_COIN),
    ("coin-cached-tokens-are-counted-twice", COIN,
     "                cached = int(det.get(\"cached_tokens\") or 0)\n"
     "                tin = max(0, tin - cached)",
     "                cached = int(det.get(\"cached_tokens\") or 0)", T_COIN),
    ("coin-a-reply-with-no-usage-raises", COIN,
     "        return (tin, tout, cached, written)\n    except Exception:\n"
     "        return (0, 0, 0, 0)",
     "        return (tin, tout, cached, written)\n    except Exception:\n"
     "        raise", T_COIN),
    ("coin-the-meter-charges-with-nothing-metering", COIN,
     "    bill = getattr(_LOCAL, \"bill\", None)\n    if bill is None:\n"
     "        return 0\n    rate = getattr(_LOCAL, \"rate\", None)",
     "    bill = getattr(_LOCAL, \"bill\", None)\n    if bill is None:\n"
     "        bill = Bill(step=\"\")\n    rate = getattr(_LOCAL, \"rate\", None)",
     T_COIN),
    ("coin-a-bill-is-rounded-up-per-call", COIN,
     "        self.usd += got\n        self.calls += 1",
     "        self.usd += coins_for_usd(got) / (COINS_PER_DOLLAR * MARKUP)\n"
     "        self.calls += 1", T_COIN),
    ("coin-a-nested-bill-does-not-give-the-outer-one-back", COIN,
     "        _LOCAL.bill = prev\n        _LOCAL.rate = rate",
     "        _LOCAL.bill = None\n        _LOCAL.rate = None", T_COIN),
    ("coin-the-flat-fee-is-billed-twice", COIN,
     "    bill = getattr(_LOCAL, \"bill\", None)\n"
     "    if bill is None:\n        return spend(coins, what or \"clean\", page)",
     "    bill = getattr(_LOCAL, \"bill\", None)\n"
     "    spend(coins, what or \"clean\", page)\n    if bill is None:\n"
     "        return coins", T_COIN),

    ("coin-the-shell-adds-nothing", COIN,
     '        print("%s TCT Coins" % show(credit(a.coins, "added from the shell")))',
     '        print("%s TCT Coins" % show(balance()))', T_COIN),
    ("coin-the-shell-takes-a-negative", COIN,
     "        if a.coins <= 0:\n"
     '            ap.error("how many coins? e.g. `add 5000`")',
     "        if False:\n"
     '            ap.error("how many coins? e.g. `add 5000`")', T_COIN),
    ("coin-just-reading-adds-some", COIN,
     '    print("%s TCT Coins" % show(balance()))\n    return 0',
     '    print("%s TCT Coins" % show(credit(1)))\n    return 0', T_COIN),

    ("coin-an-unpriced-model-is-called-priced", COIN,
     "    return (_prefix(m) or _prefix(vendor_free(m))) is not None",
     "    return True", T_COIN),
    ("coin-a-priced-model-is-called-unpriced", COIN,
     "    return (_prefix(m) or _prefix(vendor_free(m))) is not None",
     "    return False", T_COIN),
    ("coin-your-own-machine-is-called-unpriced", COIN,
     '    if (backend or "").strip().lower() in FREE_BACKENDS:\n'
     "        return True\n"
     '    m = (model or "").strip().lower()\n'
     "    return (_prefix(m) or _prefix(vendor_free(m))) is not None",
     '    m = (model or "").strip().lower()\n'
     "    return (_prefix(m) or _prefix(vendor_free(m))) is not None", T_COIN),
    ("coin-the-screen-is-never-told", PY,
     '                    "unpriced": unpriced,', '                    "unpriced": [],',
     T_COIN),
    ("coin-the-model-is-not-named", PY,
     '                    "models": {s: step_engine(p, s)[0] for s in PAID_STEPS\n'
     '                               if s != "clean"},',
     '                    "models": {},', T_COIN),
    ("coin-the-warning-is-not-drawn", JSC,
     "    warn +", "    '' +", T_COIN),
    ("coin-the-row-is-not-marked", JSC,
     "    `<div class=\"wrow${odd.has(k)?' unpriced':''}\">` +",
     '    `<div class="wrow">` +', T_COIN),

    ("coin-a-retired-model-is-offered", COIN,
     "    return [k for k in RATES if k.startswith(pre) and k not in RETIRED]",
     "    return [k for k in RATES if k.startswith(pre)]", T_STEP),
    ("coin-the-menu-is-sorted-oldest-first", COIN,
     "    return [k for k in RATES if k.startswith(pre) and k not in RETIRED]",
     "    return sorted(k for k in RATES\n"
     "                  if k.startswith(pre) and k not in RETIRED)", T_STEP),
    ("coin-a-local-provider-is-given-a-fake-menu", COIN,
     "    pre = FAMILIES.get((backend or \"\").strip().lower())\n"
     "    if not pre:\n        return []",
     "    pre = FAMILIES.get((backend or \"\").strip().lower()) or (\"\",)\n"
     "    if not pre:\n        return []", T_STEP),
    ("step-a-step-with-no-key-runs-anyway", PY,
     '    if key_for(p, back, step):\n        return ""',
     '    if True:\n        return ""', T_STEP),
    ("step-a-local-step-is-asked-for-a-key", PY,
     "    if back not in NEEDS_KEY:\n"
     '        return ""                      # local, and local wants no key',
     '    if False:\n        return ""', T_STEP),
    ("step-the-key-check-reads-the-model-as-the-provider", PY,
     "    _model, back = step_engine(p, step)\n    if back not in NEEDS_KEY:",
     "    back, _model = step_engine(p, step)\n    if back not in NEEDS_KEY:",
     T_STEP),
    ("step-the-endpoint-runs-without-a-key", PY,
     '                short = needs_key(p, "translate") or afford_run(p, "translate", idx)',
     '                short = afford_run(p, "translate", idx)', T_STEP),
    ("step-the-default-is-one-engine-for-all-three", PY,
     '    "ocr": ("gemini", "gemini-3.5-flash-lite"),',
     '    "ocr": ("anthropic", "claude-sonnet-5"),', T_STEP),
    ("step-an-old-project-loses-its-engine", PRJ,
     "        migrate_engine(self.settings, d.get(\"settings\") or {})", "        pass",
     T_STEP),
    ("step-the-migration-reads-the-merged-settings", PRJ,
     '        if str(saved.get(f"{step}_model") or "").strip():',
     '        if str(settings.get(f"{step}_model") or "").strip():', T_STEP),
    ("step-the-migration-overwrites-a-step-that-was-set", PRJ,
     '        if str(saved.get(f"{step}_model") or "").strip():\n'
     "            continue                      # this step was set up on its own",
     "        if False:\n            continue", T_STEP),
    ("step-proofread-arrives-with-no-model", PRJ,
     '            "proofread_model": "claude-sonnet-5", "proofread_backend": "anthropic",',
     '            "proofread_model": "", "proofread_backend": "",', T_STEP),
    ("step-the-menu-is-never-drawn", JSP,
     "  for(const m of names)\n"
     "    add(m, m + (priced && !priced.has(m) ? '  \u2014 not priced' : ''));",
     "  ;", T_STEP),
    ("step-the-menu-forgets-a-model-that-is-already-set", JSP,
     "  if(have && !names.includes(have)) add(have, have + '  \u2014 as set');",
     "  ;", T_STEP),
    ("step-there-is-no-way-to-type-an-odd-one", JSP,
     "  add(MODEL_OTHER, 'Other\\u2026');", "  ;", T_STEP),
    ("step-a-provider-change-leaves-the-setting-behind", JSP,
     "      box.value = names[0];\n"
     "      drawModels(step, names, priced);\n      await saveSettings();",
     "      drawModels(step, names, priced);", T_STEP),
    ("step-the-menu-is-asked-before-the-provider-is-saved", JSP,
     "    if(force) await saveSettings();", "    ;", T_STEP),
    ("step-picking-a-model-saves-nothing", JSP,
     "  box.value = sel.value;\n  box.style.display = 'none';\n  saveSettings();",
     "  box.style.display = 'none';", T_STEP),
    ("step-other-saves-an-empty-model", JSP,
     "    box.focus();\n    return;                       // nothing saved until they type one",
     "    box.focus();", T_STEP),
    ("step-changing-provider-keeps-the-old-menu", JSP,
     "  for(const s of steps){ modelsAsked.delete(s); fillModels(s, true); }",
     "  for(const s of steps){ modelsAsked.delete(s); }", T_STEP),

    # ---- and where the editor rings it up
    ("coin-nothing-is-taken-when-the-button-is-pressed", PY,
     "    coins.spend(_price, step, where, model, run=run)", "    pass", T_COIN),
    ("coin-taken-at-the-end-instead-of-the-start", PY,
     "        coins.spend(_price, step, where, model, run=run)\n"
     '        p.job["spent"] = _price',
     '        p.job["spent"] = _price', T_COIN),
    ("coin-the-refund-is-not-tied-to-the-charge", PY,
     '                                 % (step, len(boxes) - done,\n'
     '                                    "" if len(boxes) - done == 1 else "s"),\n'
     "                                 run=run)",
     '                                 % (step, len(boxes) - done,\n'
     '                                    "" if len(boxes) - done == 1 else "s"),\n'
     '                                 run=coins.new_run())', T_ACC),
    ("coin-the-metered-cost-is-charged-as-well", PY,
     "                p.job[\"cost\"] = bill.coins\n                if bill.calls:",
     "                p.job[\"cost\"] = coins.spend(bill)\n                if bill.calls:",
     T_COIN),
    ("coin-nothing-is-refunded", PY,
     "                back = coins.quote(step, boxes[done:], model, backend, ctx)",
     "                back = 0", T_COIN),
    ("coin-the-refund-is-for-the-pages-that-were-done", PY,
     "                back = coins.quote(step, boxes[done:], model, backend, ctx)",
     "                back = coins.quote(step, boxes[:done], model, backend, ctx)",
     T_COIN),
    ("coin-a-finished-run-is-refunded-anyway", PY,
     "            done = int(p.job.get(\"done\") or 0)",
     "            done = 0", T_COIN),
    ("coin-the-free-steps-are-charged-too", PY,
     "    if step not in PAID_STEPS:\n"
     "        # Not about money. `step_engine` rewrites `p.ctx` from the settings,\n"
     "        # and a Typeset or Export run has no business doing that to a context\n"
     "        # the paid steps are reading.\n"
     '        return (0, "", "")',
     '    if False:\n        return (0, "", "")', T_COIN),
    ("coin-a-run-nobody-can-pay-for-starts-anyway", PY,
     "    if price <= 0 or coins.can_afford(price):\n        return \"\"",
     '    if True:\n        return ""', T_COIN),
    ("coin-the-endpoint-starts-it-regardless", PY,
     '                short = needs_key(p, "translate") or afford_run(p, "translate", idx)\n'
     "                if short:\n"
     '                    return self._json({"error": short}, 402)',
     '                short = needs_key(p, "translate") or afford_run(p, "translate", idx)\n'
     "                if False:\n"
     '                    return self._json({"error": short}, 402)', T_COIN),
    ("coin-charged-against-the-projects-model-not-the-steps", PY,
     "    _ctx_from_settings(p, step if step in AI_STEPS else \"\")\n"
     '    return (getattr(p.ctx, "model", "") or "",',
     '    _ctx_from_settings(p, "")\n'
     '    return (getattr(p.ctx, "model", "") or "",', T_COIN),
    ("coin-every-page-is-priced-as-nine-boxes", PY,
     "        return len(p.pages[i].regions or [])",
     "        return 9", T_COIN),
    ("coin-a-local-clean-is-charged-for", PY,
     '                if int((getattr(page, "clean_stats", None) or {}).get(\n'
     '                        "neural", 0) or 0) > 0:',
     "                if True:", T_COIN),
    ("coin-the-hosted-clean-is-free", PY,
     '                if int((getattr(page, "clean_stats", None) or {}).get(\n'
     '                        "neural", 0) or 0) > 0:',
     "                if False:", T_COIN),
    ("coin-the-endpoint-can-set-a-balance", PY,
     "                if add <= 0:\n"
     '                    return self._json({"error": "how many coins?"}, 400)',
     "                if False:\n"
     '                    return self._json({"error": "how many coins?"}, 400)',
     T_COIN),
    ("coin-this-page-only-quotes-the-chapter", PY,
     '                one = _page_list(p, q.get("page", [""])[0])',
     '                one = _page_list(p, q.get("page", [""])[0], whole=True)',
     T_COIN),
    ("coin-every-page-quotes-nothing", PY,
     '                idx = _page_list(p, q.get("pages", [""])[0], whole=True)',
     '                idx = _page_list(p, q.get("pages", [""])[0])', T_COIN),
    ("coin-a-page-number-nobody-has-is-priced", PY,
     '        if piece.lstrip("-").isdigit() and 0 <= int(piece) < len(p.pages):',
     '        if piece.lstrip("-").isdigit():', T_COIN),

    # ---- and on the screen
    ("coin-the-count-is-not-drawn", JSC,
     "  n.textContent = String(coins);", "  ;", T_COIN),
    ("coin-the-live-count-is-stored-and-falls-twice", JSC,
     "function coinsSpending(spent){\n  if(!wallet) return;\n"
     "  paintCount(wallet.balance - (spent||0));\n}",
     "function coinsSpending(spent){\n  if(!wallet) return;\n"
     "  wallet.balance -= (spent||0);\n  paintCount(wallet.balance);\n}", T_COIN),
    ("coin-buying-goes-nowhere", JSC,
     "  window.open(url, '_blank', 'noopener');", "  ;", T_COIN),
    ("coin-the-panel-still-tops-up", JSC,
     "`<div class=\"wtop\"><button class=\"pri\" onclick=\"buyCoins()\">` +\n"
     "    `Buy coins</button></div>`;",
     "`<div class=\"wtop\"><button class=\"pri\" onclick=\"topUp(500)\">` +\n"
     "    `+500</button></div>`;", T_COIN),
    ("coin-the-dialog-shows-no-price", JS,
     "  put(all, (scopeQuote.prices||{})[step]);\n"
     "  put(one, (scopeQuote.one||{})[step]);",
     "  put(all, null);\n  put(one, null);", T_COIN),
    ("coin-the-dialog-shows-the-same-price-twice", JS,
     "  put(one, (scopeQuote.one||{})[step]);",
     "  put(one, (scopeQuote.prices||{})[step]);", T_COIN),
    ("coin-the-last-steps-price-lingers", JS,
     "    const had = el.querySelector('.scpcoin');\n    if(had) had.remove();",
     "    const had = el.querySelector('.scpcoin');", T_COIN),
    ("coin-the-dialog-prices-the-whole-chapter", JS,
     "  return `?pages=${picked.join(',')}&page=${cur}`;",
     "  return `?page=${cur}`;", T_COIN),
    ("coin-face-is-a-blank-disc", HTML,
     '      <path d="M7 10 L18 10 L32 30 L46 10 L57 10 L57 46 L46.5 46 L46.5 26.5 L35.5 42 L28.5 42 L17.5 26.5 L17.5 47 L11.5 60 L7 47 Z" fill="#7a4a00"/>\n',
     '', T_COIN),
    ("coin-face-is-not-the-logo", HTML,
     '      <path d="M7 10 L18 10 L32 30 L46 10 L57 10 L57 46 L46.5 46 L46.5 26.5 L35.5 42 L28.5 42 L17.5 26.5 L17.5 47 L11.5 60 L7 47 Z" fill="#7a4a00"/>',
     '      <path d="M20 20 L44 20 L44 44 L20 44 Z" fill="#7a4a00"/>', T_COIN),
    ("coin-the-count-draws-its-own-coin", HTML,
     '<svg class="coinface" width="15" height="15" aria-hidden="true"><use\n'
     '            href="#tctcoin"/></svg>',
     '<svg class="coinface" width="15" height="15" aria-hidden="true"><circle\n'
     '            cx="8" cy="8" r="7" fill="#ffc400"/></svg>', T_COIN),
    ("coin-the-price-wears-a-gold-dot-instead", JS,
     '`<span class="scpcoin">${n} <svg class="coinpip" width="13" height="13"` +\n'
     "      ` aria-hidden=\"true\"><use href=\"#tctcoin\"/></svg></span>`);",
     '`<span class="scpcoin">${n} <i class="coindot"></i></span>`);', T_COIN),
    ("coin-count-lives-with-the-page-tools", HTML,
     '  <div class="side coinwrap">', '  <div class="side right coinwrap" style="display:none">',
     T_COIN),

    # ---- the last resort breaks where the author did, too
    ("plain-wrap-on-spaces-only", TS,
     "    toks, glue = author_break_tokens(text)\n    if not toks:\n"
     "        return None",
     "    toks, glue = text.split(), [False] * len(text.split())\n"
     "    if not toks:\n        return None", T_DASH),
    ("plain-wrap-puts-a-space-back-in-the-word", TS,
     "            trial = tk if not cur else (cur + tk if glue[k] else cur + \" \" + tk)\n"
     "            if _text_w(path, size, trial) <= avail_w or not cur:",
     "            trial = tk if not cur else cur + \" \" + tk\n"
     "            if _text_w(path, size, trial) <= avail_w or not cur:", T_DASH),
    ("plain-wrap-breaks-every-piece-onto-its-own-line", TS,
     "            trial = tk if not cur else (cur + tk if glue[k] else cur + \" \" + tk)\n"
     "            if _text_w(path, size, trial) <= avail_w or not cur:",
     "            trial = tk if not cur else (cur + tk if glue[k] else cur + \" \" + tk)\n"
     "            if not cur:", T_DASH),
    ("plain-wrap-lets-one-piece-hang-out-of-the-box", TS,
     "            if _text_w(path, size, cur) > avail_w:\n"
     "                ok = False          # one unbreakable piece is wider than the box",
     "            if False:\n"
     "                ok = False          # one unbreakable piece is wider than the box",
     T_DASH),
    ("flag-fires-even-at-the-minimum", TS,
     "        if lay.font_size < cfg.min_font:\n"
     "            region.flagged = (\"overflow: shrunk below the minimum font size \"",
     "        if True:\n"
     "            region.flagged = (\"overflow: shrunk below the minimum font size \"",
     T_DASH),
    ("flag-never-fires", TS,
     "        if lay.font_size < cfg.min_font:\n"
     "            region.flagged = (\"overflow: shrunk below the minimum font size \"",
     "        if False:\n"
     "            region.flagged = (\"overflow: shrunk below the minimum font size \"",
     T_DASH),

    # ---- the substitution is on out of the box
    ("subs-switch-never-loads", JSP,
     "  $('substitutes').checked=!!proj.settings.substitutes;",
     "  ;", T_FONT),
    ("subs-switch-always-drawn-on", JSP,
     "  $('substitutes').checked=!!proj.settings.substitutes;",
     "  $('substitutes').checked=true;", T_FONT),
    ("subs-switch-never-saves", JSP,
     "    substitutes:$('substitutes').checked,",
     "    substitutes:proj.settings.substitutes,", T_FONT),
    ("subs-switch-saves-the-default-whatever-you-do", JSP,
     "    substitutes:$('substitutes').checked,",
     "    substitutes:true,", T_FONT),
    ("subs-no-switch-on-the-screen", HTML,
     '<input type="checkbox" id="substitutes" onchange="saveSettings()">',
     '<input type="checkbox" id="substitutes_" onchange="saveSettings()">',
     T_FONT),

    # ---- the default face is a path everything else can match
    ("font-the-env-override-is-returned-as-typed", TYP,
     "        return os.path.abspath(env)", "        return env", T_FONTPATH),

    # ---- the account the coins live in
    ("acct-a-placeholder-key-counts-as-configured", ACC,
     '    if "YOUR" in (got.get("apiKey") or "").upper():\n'
     '        got["apiKey"] = ""',
     '    pass', T_ACC),
    ("acct-the-environment-does-not-win", ACC,
     "        if os.environ.get(env):\n            got[key] = os.environ[env]",
     "        if False:\n            got[key] = os.environ[env]", T_ACC),
    ("acct-signed-in-without-a-project", ACC,
     'return bool(configured() and _read().get("refreshToken"))',
     'return bool(_read().get("refreshToken"))', T_ACC),
    ("acct-the-token-file-is-world-readable", ACC,
     "os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600",
     "os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644", T_ACC),
    ("acct-the-read-cache-leaks-into-the-token-file", ACC,
     '                json.dump({k: v for k, v in d.items() '
     'if not k.startswith("_")},',
     "                json.dump(d,", T_ACC),
    ("acct-an-expired-token-is-used-anyway", ACC,
     'if d.get("idToken") and float(d.get("expires") or 0) > time.time() + EARLY:',
     'if d.get("idToken"):', T_ACC),
    ("acct-no-margin-before-a-token-expires", ACC,
     "EARLY = 60.0", "EARLY = 0.0", T_ACC),
    ("acct-the-call-carries-no-token", ACC,
     'got = _post(url, {"data": data or {}}, token())',
     'got = _post(url, {"data": data or {}})', T_ACC),
    ("acct-a-shortfall-is-lost-on-the-way-through", ACC,
     'return NotEnough("Not enough coins.", d.get("short"), d.get("balance"))',
     'return AccountError("Not enough coins.", "not-enough")', T_ACC),
    ("acct-a-signed-out-session-reads-as-an-ordinary-error", ACC,
     'if status == "UNAUTHENTICATED" or http == 401:\n        return NotSignedIn()',
     'if False:\n        return NotSignedIn()', T_ACC),
    ("acct-a-taken-name-loses-the-new-account", ACC,
     "        try:\n            claim_username(username)\n"
     "        except AccountError:\n            pass",
     "        claim_username(username)", T_ACC),
    ("acct-a-fresh-balance-is-allowed-to-be-stale", ACC,
     "    if fresh:", "    if False:", T_ACC),
    ("acct-a-balance-is-fetched-on-every-read", ACC,
     "    elif time.time() - float(d.get(\"checked\") or 0) > FRESH_FOR:",
     "    elif True:", T_ACC),
    ("acct-a-spend-invents-its-own-run-every-time", ACC,
     '"run": run or new_run()}', '"run": new_run()}', T_ACC),
    ("acct-a-refund-with-no-run-is-sent-anyway", ACC,
     "    if coins <= 0 or not run:\n        return 0\n"
     '    got = _post' if False else
     "    if coins <= 0 or not run:", "    if coins <= 0:", T_ACC),
    ("acct-spending-nothing-is-still-a-request", ACC,
     "    coins = int(coins or 0)\n    if coins <= 0:\n        return 0\n"
     '    got = call("spendCoins"',
     '    coins = int(coins or 0)\n    got = call("spendCoins"', T_ACC),

    # ---- which purse a spend lands in
    ("coin-signed-in-but-charging-the-local-wallet", COIN,
     "    if remote():\n        # `run` is what makes this happen once.",
     "    if False:\n        # `run` is what makes this happen once.", T_ACC),
    ("coin-being-signed-in-is-ignored-and-the-local-wallet-is-used", COIN,
     "    return account.signed_in()", "    return False", T_ACC),
    ("coin-coins-can-be-minted-into-an-account", COIN,
     '        if not run:\n            raise account.AccountError(\n'
     '                "Coins are bought on the website.", "no-minting")',
     "        if not run:\n            return account.balance()", T_ACC),
    ("coin-affording-a-run-trusts-the-cache", COIN,
     "            return account.balance(fresh=True) >= int(coins or 0)",
     "            return account.balance() >= int(coins or 0)", T_ACC),
    ("coin-an-unreachable-server-can-afford-anything", COIN,
     "        except account.AccountError:\n            return False",
     "        except account.AccountError:\n            return True", T_ACC),
    ("coin-the-screen-is-not-told-which-purse-it-is", COIN,
     '                "configured": account.configured(), "signed_in": False}',
     "                }", T_ACC),

    # ---- the context, and the one decision behind it
    ("ctx-a-full-chapter-run-is-sent-a-context-anyway", PY,
     "    if not idx or len(idx) >= len(p.pages):\n        return None",
     "    if not idx:\n        return None", T_CTX),
    ("ctx-the-pages-being-translated-are-sent-back-to-themselves", PY,
     "        if k in skip:\n            continue",
     "        if False:\n            continue", T_CTX),
    ("ctx-a-page-with-no-translation-yet-contributes-nothing", PY,
     '            t = (r.get("dst_text") or "").strip() or (r.get("src_text") or "").strip()',
     '            t = (r.get("dst_text") or "").strip()', T_CTX),
    ("ctx-the-source-line-wins-over-the-finished-one", PY,
     '            t = (r.get("dst_text") or "").strip() or (r.get("src_text") or "").strip()',
     '            t = (r.get("src_text") or "").strip() or (r.get("dst_text") or "").strip()',
     T_CTX),
    ("ctx-what-is-charged-is-not-what-is-sent", PY,
     '    return sum(len(e.get("lines") or []) for e in (run_context(p, indices) or []))',
     "    return sum(page_boxes(p, i) for i in range(len(p.pages)))", T_CTX),
    ("ctx-reading-a-page-pays-for-a-chapter-it-never-sees", PY,
     '    if step != "translate":\n        return 0',
     "    if False:\n        return 0", T_CTX),

    # ---- every glossary term says what it is
    ("gloss-a-bare-name-gets-in", TR,
     '        if not note:\n            refused.append(f"{name} (no description — say what it is)")\n            continue',
     "        if not note:\n            pass", T_GLOSS),
    ("gloss-a-bare-name-is-dropped-silently", TR,
     '            refused.append(f"{name} (no description — say what it is)")\n            continue',
     "            continue", T_GLOSS),
    ("gloss-an-empty-row-is-never-filled-in", TR,
     "        if have is not None:\n            if gloss_note(have):\n                continue",
     "        if have is not None:\n            continue", T_GLOSS),
    ("gloss-a-later-page-re-words-a-settled-term", TR,
     "            if gloss_note(have):\n                continue",
     "            if False:\n                continue", T_GLOSS),
    ("gloss-filling-a-row-in-renames-the-thing", TR,
     "            name = gloss_name(have) or name  # fill the note in, keep the name",
     "            pass  # fill the note in, keep the name", T_GLOSS),
    ("gloss-a-hyphen-in-a-name-is-read-as-a-description", TR,
     '_GLOSS_DASH = re.compile(r"\\s+[—–-]\\s+(.+)$")',
     '_GLOSS_DASH = re.compile(r"[—–-]\\s*(.+)$")', T_GLOSS),
    ("gloss-the-name-is-cut-at-the-last-bracket", TR,
     '    return _GLOSS_SPLIT.split(str(v or ""), 1)[0].strip()',
     '    return _GLOSS_SPLIT.split(str(v or ""))[-1].strip()', T_GLOSS),
    ("gloss-a-refusal-is-never-reported", TR,
     '            if gl_refused:\n                data["glossary_refused"] = gl_refused',
     "            pass", T_GLOSS),

    # ---- the estimate that learns
    ("learn-a-fresh-install-invents-a-correction", COIN,
     "    return (_clamp(rin / pin) if pin and rin else 1.0,\n"
     "            _clamp(rout / pout) if pout and rout else 1.0)",
     "    return (_clamp(rin / pin) if pin and rin else 2.0,\n"
     "            _clamp(rout / pout) if pout and rout else 2.0)", T_LEARN),
    ("learn-the-correction-is-never-applied", COIN,
     "    din, dout = drift(step, model, backend)",
     "    din, dout = 1.0, 1.0", T_LEARN),
    ("learn-one-correction-does-for-both-sides", COIN,
     "    return r.usd(tin=int(round(tin * din)), cached=int(round(cached * din)),\n"
     "                 tout=int(round(tout * dout)))",
     "    return r.usd(tin=int(round(tin * din)), cached=int(round(cached * din)),\n"
     "                 tout=int(round(tout * din)))", T_LEARN),
    ("learn-cached-tokens-count-only-on-the-real-side", COIN,
     "        pin += tin + cached",
     "        pin += tin", T_LEARN),
    ("learn-one-wild-run-runs-away-with-the-price", COIN,
     "    lo, hi = DRIFT_CLAMP\n    return max(lo, min(hi, float(x)))",
     "    return float(x)", T_LEARN),
    ("learn-a-one-page-run-gets-a-vote", COIN,
     "        if boxes < DRIFT_MIN_BOXES or pages <= 0:\n            continue",
     "        if pages <= 0:\n            continue", T_LEARN),
    ("learn-every-run-ever-still-votes", COIN,
     "        if seen >= DRIFT_RUNS:\n            break",
     "        if False:\n            break", T_LEARN),
    ("learn-the-runs-are-averaged-instead-of-summed", COIN,
     "        pin += tin + cached\n        pout += tout",
     "        pin = tin + cached\n        pout = tout", T_LEARN),
    ("learn-another-models-runs-vote-on-this-one", COIN,
     '        if (e.get("model") or "").strip().lower() != model:\n            continue',
     "        if False:\n            continue", T_LEARN),
    ("learn-another-steps-runs-vote-on-this-one", COIN,
     '        if e.get("kind") != "meter" or e.get("step") != step:\n            continue',
     '        if e.get("kind") != "meter":\n            continue', T_LEARN),
    ("learn-the-correction-moves-under-a-running-job", COIN,
     "    at = getattr(_STEADY, \"at\", None)\n"
     "    key = (step, (model or \"\").strip().lower(), (backend or \"\").strip().lower())\n"
     "    if at is not None and key in at:\n        return at[key]",
     "    at = None\n"
     "    key = (step, (model or \"\").strip().lower(), (backend or \"\").strip().lower())",
     T_LEARN),
    ("learn-the-meter-does-not-say-how-big-the-run-was", PY,
     "                               step=step, backend=backend, ctx=ctx,\n"
     "                               boxes=sum(boxes[:done]), pages=done)",
     "                               step=step, backend=backend, ctx=ctx)", T_LEARN),
    ("learn-a-cancelled-run-claims-every-page", PY,
     "                               boxes=sum(boxes[:done]), pages=done)",
     "                               boxes=sum(boxes), pages=len(boxes))", T_LEARN),

    # ---- a menu you can trust
    ("menu-offers-what-the-key-cannot-reach", PY,
     "    have = set(_reachable(back, url, key))\n"
     "    both = [m for m in priced if m in have]\n"
     "    return both or priced",
     "    return priced", T_MENU),
    ("menu-offers-what-cannot-be-priced", PY,
     "    have = set(_reachable(back, url, key))\n"
     "    both = [m for m in priced if m in have]\n"
     "    return both or priced",
     "    return _reachable(back, url, key)", T_MENU),
    ("menu-an-empty-crossing-leaves-nothing-to-choose", PY,
     "    return both or priced",
     "    return both", T_MENU),
    ("menu-read-text-offers-a-model-that-cannot-see", PY,
     '    priced = [m for m in coins.models_for(back)\n'
     '              if step != "ocr" or coins.sees(m)]',
     "    priced = list(coins.models_for(back))", T_MENU),
    ("menu-a-blind-model-is-called-sighted", COIN,
     "    return not vendor_free(model).startswith(NO_SIGHT)",
     "    return True", T_MENU),
    ("menu-a-key-is-asked-for-that-does-not-exist", PY,
     "    if not key:\n        return []",
     "    if False:\n        return []", T_MENU),
    ("menu-nothing-is-ever-remembered", PY,
     "    if hit and time.time() - hit[0] < MENU_TTL:\n        return hit[1]",
     "    if False:\n        return hit[1]", T_MENU),
    ("menu-the-answer-is-remembered-for-ever", PY,
     "    if hit and time.time() - hit[0] < MENU_TTL:",
     "    if hit:", T_MENU),
    ("menu-the-cache-is-keyed-on-the-address-alone", PY,
     '    return (url or "", hashlib.sha256((key or "").encode()).hexdigest()[:16])',
     '    return (url or "", "")', T_MENU),
    ("menu-the-live-key-is-the-cache-key", PY,
     '    return (url or "", hashlib.sha256((key or "").encode()).hexdigest()[:16])',
     '    return (url or "", key or "")', T_MENU),
    ("menu-a-saved-setting-leaves-the-old-answer-standing", PY,
     "                    _MENU_CACHE.clear()",
     "                    pass", T_MENU),
    ("orouter-a-namespaced-slug-is-priced-as-unknown", COIN,
     "    return _prefix(m) or _prefix(vendor_free(m)) or UNKNOWN",
     "    return _prefix(m) or UNKNOWN", T_MENU + T_COIN),
    ("orouter-the-name-is-cut-at-the-last-slash", COIN,
     '    return m.split("/", 1)[1] if "/" in m else m',
     '    return m.rsplit("/", 1)[-1]', T_MENU + T_COIN),
    ("orouter-the-whole-name-is-never-looked-up-first", COIN,
     "    return _prefix(m) or _prefix(vendor_free(m)) or UNKNOWN",
     "    return _prefix(vendor_free(m)) or UNKNOWN", T_MENU + T_COIN),
    ("orouter-a-bought-model-never-thinks", COIN,
     "    return vendor_free((model or \"\").strip().lower()).startswith(THINKS)",
     "    return (model or \"\").strip().lower().startswith(THINKS)", T_MENU + T_COIN),
    ("orouter-a-bought-cache-is-never-priced", COIN,
     "            if vendor_free(model).startswith(MARKS_CACHE) else 0)",
     '            if (model or "").startswith(MARKS_CACHE) else 0)', T_MENU + T_COIN),
    ("orouter-the-provider-prefix-is-stripped-off-the-listing", TR,
     '        out.append(name[len("models/"):] if name.startswith("models/") else name)',
     '        out.append(name.split("/")[-1])', T_STEP),

    # ---- one key per service
    ("keys-a-stale-step-key-beats-the-service-box", PY,
     '    ours = str(p.settings.get(f"key_{back}") or "").strip()\n'
     "    if ours:\n        return ours",
     '    ours = str(p.settings.get(f"key_{back}") or "").strip()', T_KEYS),
    ("keys-a-step-key-is-handed-to-another-service", PY,
     '        if (p.settings.get(f"{s}_backend") or "").strip().lower() != back:\n'
     "            continue",
     "        if False:\n            continue", T_KEYS),
    ("keys-an-old-project-loses-its-key", PRJ,
     "        migrate_keys(self.settings, d.get(\"settings\") or {})",
     "        pass", T_KEYS),
    ("keys-the-migration-overwrites-a-newer-key", PRJ,
     '        if str(settings.get(f"key_{back}") or "").strip():\n            continue',
     "        if False:\n            continue", T_KEYS),
    ("keys-a-gone-service-is-migrated-anyway", PRJ,
     "        if not key or back not in SERVICES:\n            continue",
     "        if not key:\n            continue", T_KEYS),
    ("keys-a-key-is-sent-back-to-the-browser", PRJ,
     '                         **{f"key_{s}": ("set" if self.settings.get(f"key_{s}")\n'
     '                                         else "")\n'
     "                            for s in SERVICES}},",
     '                         **{f"key_{s}": self.settings.get(f"key_{s}")\n'
     "                            for s in SERVICES}},", T_KEYS),

    # ---- the bar holds still
    ("bar-the-strip-grows-with-the-message", CSS,
     ".jobcol{flex:0 0 250px;width:250px;",
     ".jobcol{flex:1 1 auto;", T_BAR),
    ("bar-the-message-is-not-cut", CSS,
     " white-space:nowrap;overflow:hidden;text-overflow:ellipsis;",
     " white-space:nowrap;", T_BAR),
    ("bar-the-whole-message-is-nowhere", PIPE,
     "  job.title = full;\n  job._full = full;",
     "  job.title = '';\n  job._full = '';", T_BAR),
    ("bar-clicking-says-nothing", PIPE,
     "  if(full && typeof toast === 'function') toast(full);",
     "  if(false) toast(full);", T_BAR),
    ("bar-a-warning-is-offered-when-there-is-none", PIPE,
     "  const full = j.error || j.warn || '';",
     "  const full = j.error || j.warn || 'Ready';", T_BAR),

    # ---- and the word
    ("word-a-wrap-hides-the-verb", "tests/test_the_word_is_typesetting.py",
     '    out = re.sub(r"\\n\\s*(?:#+|//+|\\*+)?\\s*", " ", text)',
     "    out = text", T_WORD),
    ("word-the-verb-is-allowed-again", TYP,
     "    absolute_floor: int = 7     # never typeset smaller than this, ever",
     "    absolute_floor: int = 7     # never letter smaller than this, ever",
     T_WORD),
    ("word-the-headline-goes-back", "site/index.html",
     "<h1>Translate, clean and typeset a chapter",
     "<h1>Translate, clean and letter a chapter", T_WORD),
    ("word-the-noun-comes-back", TR,
     "  sentence. Typeset it as a typesetter would DRAW it — bare.",
     "  sentence. Letter it as a letterer would DRAW it — bare.", T_WORD),

    # ---- the landing page
    ("site-a-missing-picture-ships-as-a-broken-image", SITE,
     "    if have(name):\n        return f'<img src=\"assets/{name}\" alt=\"{alt}\" loading=\"lazy\">'",
     "    if True:\n        return f'<img src=\"assets/{name}\" alt=\"{alt}\" loading=\"lazy\">'",
     T_SITE),
    ("site-a-hole-does-not-say-which-file-it-wants", SITE,
     "            f'<span class=\"sn\">{name}</span>'",
     "            f'<span class=\"sn\">picture</span>'", T_SITE),
    ("site-a-hole-does-not-say-what-to-photograph", SITE,
     "            f'<span class=\"sw\">{want or alt}</span></div>')",
     "            f'</div>')", T_SITE),
    ("site-nobody-is-told-what-is-still-wanted", SITE,
     "    WANTED.append((name, want or alt))\n",
     "", T_SITE),
    # ---- what a customer sees
    #
    # The first of these is the bug that started the rewrite: lee refunded a
    # live $4.99 purchase and the page told him he had been GIVEN 500 coins.
    ("look-a-clawback-is-shown-as-money-coming-in", ACC,
     "const IN = new Set(['credit', 'refund']);",
     "const IN = new Set(['credit', 'refund', 'clawback']);", T_LOOK),
    ("look-a-clawback-is-shown-with-no-sign-at-all", ACC,
     "const plus = IN.has(r.kind);",
     "const plus = r.kind !== 'spend';", T_LOOK),
    ("look-the-ledger-says-pack-pack1", ACC,
     "    (m, id) => (PACKS[id] ? 'the ' + PACKS[id] + ' pack' : m));",
     "    (m, id) => m);", T_LOOK),
    ("look-the-refunded-tag-is-read-out-twice", ACC,
     "  what = what.replace(/\\s*[-|\\u2013\\u2014]\\s*refunded\\s*$/i, '');",
     "", T_LOOK),
    ("look-links-are-underlined-again", SCSS,
     "a{color:var(--link);text-decoration:none}",
     "a{color:var(--link)}", T_LOOK),
    ("look-following-the-system-is-stored-as-a-choice", APPJS,
     "    if (want === 'auto') localStorage.removeItem('tct-theme');\n"
     "    else localStorage.setItem('tct-theme', want);",
     "    localStorage.setItem('tct-theme', want);", T_LOOK),
    ("look-the-theme-is-not-remembered", APPJS,
     "  if (want === 'auto') delete document.documentElement.dataset.theme;\n"
     "  else document.documentElement.dataset.theme = want;",
     "  if (want !== 'auto') document.documentElement.dataset.theme = want;",
     T_LOOK),
    ("look-a-page-whose-script-never-arrives-stays-invisible", APPJS,
     "  document.documentElement.dataset.chrome = '1';", "", T_LOOK),
    ("look-the-calculator-forgets-the-chapter-context", COSTS,
     "    total += coinsFor(pages * model[s][0] + boxes * model[s][1]\n"
     "                      + pages * boxes * model[s][2]);",
     "    total += coinsFor(pages * model[s][0] + boxes * model[s][1]);",
     T_LOOK),
    ("look-the-calculator-rounds-once-instead-of-per-step", COSTS,
     "export function quote(model, pages, boxes, steps) {\n  let total = 0;",
     "export function quote(model, pages, boxes, steps) {\n  let total = 0.4;",
     T_LOOK),


    # ---- the price ids that go into Firestore by hand
    #
    # `seed.js` is not run by any test — it needs a Firestore. What IS tested
    # is its SOURCE, because the property that matters is an ordering: the
    # check happens before the write. These four mutants are the four ways to
    # break that ordering while leaving a file that still looks careful.
    ("seed-a-pasted-placeholder-is-written-as-a-price", SEED,
     "if (junk.length) {",
     "if (false) {", T_SEED),
    ("seed-a-bad-id-is-a-warning-and-the-run-goes-on", SEED,
     "  console.error('Nothing was written.');\n  process.exit(1);",
     "  console.error('Nothing was written.');", T_SEED),
    ("seed-the-check-runs-after-the-writes", SEED,
     "const junk = Object.entries(args)",
     "const junk = [].concat(", T_SEED),
    ("seed-the-shape-check-is-copied-instead-of-shared", SEED,
     "import { PACKS, looksLikePriceId } from './purse.js';",
     "import { PACKS } from './purse.js';\n"
     "const looksLikePriceId = (s) => /^price_/.test(String(s || ''));", T_SEED),

    ("site-the-page-still-sells-a-service-that-is-gone", SITE,
     "<b>Claude, Google AI Studio or OpenRouter</b> —",
     "<b>Claude, Gemini, OpenAI or OpenRouter</b> —", T_SITE),
    ("site-manhwa-is-numbered-like-manga", SITE,
     '        "dir": "Left to right",\n'
     '        "line": "Webtoon strips get cut into pages before anything else runs.",',
     '        "dir": "Right to left",\n'
     '        "line": "Webtoon strips get cut into pages before anything else runs.",',
     T_SITE),
    ("site-a-format-admits-nothing", SITE,
     '        "rough": [\n'
     '            ("The local Korean reader is an extra install",',
     '        "rough": [] and [\n'
     '            ("The local Korean reader is an extra install",', T_SITE),
    ("site-the-reveal-hides-the-page-with-no-javascript", SITE,
     ".nojs .rise{{opacity:1;transform:none}}",
     "/* .nojs .rise */", T_SITE),
    ("site-an-anchor-lands-under-the-header", SITE,
     "[id]{{scroll-margin-top:84px}}",
     "[id]{{scroll-margin-top:0}}", T_SITE),
    ("site-the-tabs-cannot-be-moved-through-by-keyboard", SITE,
     "      var n = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : -1;",
     "      var n = -1;", T_SITE),
    ("site-nobody-built-it", SITE,
     '<span class="built">Built by <b>LMB Technology</b></span>',
     '<span class="built"></span>', T_SITE),
    ("site-the-webtoon-answer-goes-back-to-do-it-yourself", SITE,
     '"A chapter uploaded as identical tiles is re-cut into pages near 2,400px "',
     '"Long webtoon strips are the weak spot. "', T_SITE),

    # ---- the story is a thing you can switch off
    ("story-the-sheets-are-sent-anyway", TR,
     '        **({"series_context": ctx.synopsis,\n'
     '            "glossary": ctx.glossary} if story else {}),',
     '        "series_context": ctx.synopsis,\n'
     '        "glossary": ctx.glossary,', T_STORY),
    ("story-the-character-sheet-is-sent-anyway", TR,
     '        **({"characters": getattr(ctx, "characters", {}) or {}}\n'
     "           if story else {}),",
     '        "characters": getattr(ctx, "characters", {}) or {},', T_STORY),
    ("story-the-model-is-not-told-what-to-leave-out", TR,
     '        **({"do_not_return": off} if off else {}),',
     "", T_STORY),
    ("story-a-switched-off-sheet-is-written-to-anyway", TR,
     "        if story and getattr(ctx, \"learn_terms\", True) and isinstance(gl, dict):",
     "        if isinstance(gl, dict):", T_STORY),
    ("story-a-switched-off-cast-is-written-to-anyway", TR,
     "        if story and getattr(ctx, \"learn_characters\", True) and isinstance(adds, dict):",
     "        if isinstance(adds, dict):", T_STORY),
    ("story-the-two-ticks-are-really-one", TR,
     "        if story and getattr(ctx, \"learn_terms\", True) and isinstance(gl, dict):",
     "        if story and getattr(ctx, \"learn_characters\", True) and isinstance(gl, dict):",
     T_STORY),
    ("story-a-speaker-arrives-anyway", TR,
     '            sp = item.get("speaker") if getattr(ctx, "name_speakers", True) else None',
     '            sp = item.get("speaker")', T_STORY),
    ("story-a-sheet-nobody-keeps-is-still-complained-about", TR,
     "            if not story or not r.speaker or is_generic_speaker(r.speaker):",
     "            if not r.speaker or is_generic_speaker(r.speaker):", T_STORY),
    ("story-an-old-project-loses-its-story", PY,
     '    p.ctx.story = s.get("story", True) is not False',
     '    p.ctx.story = bool(s.get("story"))', T_STORY),
    ("story-the-screen-reads-a-missing-switch-as-off", JSP,
     "    const el=$(k); if(el) el.checked = proj.settings[k] !== false; });",
     "    const el=$(k); if(el) el.checked = !!proj.settings[k]; });", T_STORY),

    # ---- and where the manual switch lives
    ("manual-the-switch-is-not-beside-the-text", HTML,
     '      <input type="checkbox" id="manual_translate" onchange="saveSettings()">',
     '      <input type="checkbox" id="manual_translate_x" onchange="saveSettings()">',
     T_MANUAL),
    ("manual-the-switch-is-in-two-places-at-once", HTML,
     '        <h2 class="set-h">Translation engine</h2>',
     '        <h2 class="set-h">Translation engine</h2>\n'
     '        <input type="checkbox" id="manual_translate">', T_MANUAL),
    # ---- what a menu may offer: usable, current, one per price, and not a
    # thing your own key can already reach
    ("trim-a-text-to-speech-model-is-offered-as-a-translator", COIN,
     "    return not (parts & NOT_A_TRANSLATOR) and not (parts & NOT_SETTLED)",
     "    return not (parts & NOT_SETTLED)", T_TRIM),
    ("trim-a-preview-is-offered", COIN,
     "    return not (parts & NOT_A_TRANSLATOR) and not (parts & NOT_SETTLED)",
     "    return not (parts & NOT_A_TRANSLATOR)", T_TRIM),
    ("trim-the-word-is-matched-as-a-substring", COIN,
     '    parts = set(re.split(r"[-_./]", vendor_free(model)))',
     "    parts = set()", T_TRIM),
    ("trim-nothing-is-ever-too-old", COIN,
     "    if major != top - 1:\n        return False",
     "    if major != top - 1:\n        return True", T_TRIM),
    ("trim-the-whole-previous-generation-is-kept", COIN,
     "    return minor >= max(x[2] for x in seen if x[1] == major)",
     "    return True", T_TRIM),
    ("trim-two-models-at-one-price-are-both-offered", COIN,
     "        if k in seen:\n            continue",
     "        if False:\n            continue", T_TRIM),
    ("trim-the-price-trim-happens-before-the-key-is-asked", PY,
     "    return offer if free else coins.one_per_price(offer)",
     "    return offer", T_TRIM),
    ("trim-the-written-down-menu-is-not-trimmed", PY,
     "    known = ([m for m in coins.models_for(back) if usable(m)] if free\n"
     "             else coins.offered(back, step))",
     "    known = [m for m in coins.models_for(back) if usable(m)]", T_TRIM),
    ("orouter-what-your-own-key-runs-is-offered-twice", PY,
     '        if back == "openrouter" and coins.vendor_free(m) in direct:\n'
     "            return False",
     "        if False:\n            return False", T_TRIM),
    ("orouter-a-direct-service-defers-to-the-others-too", PY,
     '        if back == "openrouter" and coins.vendor_free(m) in direct:',
     "        if coins.vendor_free(m) in direct:", T_TRIM),
    ("orouter-nobody-asks-what-the-other-keys-can-reach", PY,
     "                    elsewhere = []\n"
     '                    if back == "openrouter":',
     "                    elsewhere = []\n"
     "                    if False:", T_TRIM),
    ("orouter-the-maker-menu-never-appears", JSP,
     "    if(makers.length > 1){",
     "    if(false){", T_TRIM),
    ("orouter-choosing-a-maker-shows-every-model-anyway", JSP,
     "  const shown = names.filter(m => !only || !vendorOf(m) || vendorOf(m) === only);",
     "  const shown = names;", T_TRIM),
    ("orouter-the-maker-menu-snaps-back-to-the-model-that-is-set", JSP,
     "      const want = ven.value || vendorOf(have) || makers[0];",
     "      const want = vendorOf(have) || ven.value || makers[0];", T_TRIM),
    # There is deliberately NO mutant for "the switch sits below the list
    # instead of above it". The test asserts the order, but a mutation here is
    # one find-and-replace and moving a block of markup is not — every version
    # of it was an attribute change that moved nothing, and a mutant that
    # cannot express the fault proves only that the suite survives a no-op.
]






def run(tests):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    r = subprocess.run([sys.executable, "-m", "pytest", *tests, "-q",
                        "-p", "no:randomly", "-x", "-n", "2"],
                       cwd=PKG, env=env, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout or "")[-400:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", default="")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    picked = [m for m in MUTANTS if a.k in m[0]]
    if a.list:
        for m in picked:
            print(m[0])
        return 0

    # A run killed part-way — a timeout, a Ctrl-C, a `pkill` — never reaches
    # its `finally`, and the mutant it was holding stays on disk. Everything
    # measured afterwards is then measured against it, silently: one such
    # leftover sat in `static/editor.html` for an hour and turned the coin in
    # the top bar into a plain yellow disc.
    #
    # So: before touching anything, look for a file that holds some mutant's
    # REPLACEMENT where its original should be, and refuse to start.
    stale = [(n, f) for n, f, fi, rp, _t in MUTANTS
             if rp and (PKG / f).exists()
             and fi not in (PKG / f).read_text(encoding="utf-8")
             and rp in (PKG / f).read_text(encoding="utf-8")]
    if stale:
        print("REFUSING TO RUN — a previous run left a mutant on disk:")
        for n, f in stale:
            print(f"  {n}\n      in {f}")
        print("\nPut those back before measuring anything.")
        return 2

    survivors = []
    for name, rel, find, repl, tests in picked:
        f = PKG / rel
        src = f.read_text(encoding="utf-8")
        if src.count(find) != 1:
            print(f"SKIP  {name}: anchor appears {src.count(find)}×")
            continue
        try:
            f.write_text(src.replace(find, repl), encoding="utf-8")
            ok, tail = run(tests)
        finally:
            f.write_text(src, encoding="utf-8")
        if ok:
            survivors.append(name)
            print(f"SURVIVED  {name}")
        else:
            print(f"caught    {name}")
    print()
    print(json.dumps({"total": len(picked), "survivors": survivors}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
