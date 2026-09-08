#!/usr/bin/env python3
"""Break the code on purpose and see whether the tests notice.

A test that passes proves nothing on its own - it passes against the right
code and, far too often, against the wrong code as well. So each mutation
below is a small, plausible wrong version of a line that was just written: a
guard dropped, a comparison flipped, a field left unset. The tests are run
against it. A mutation the tests still pass is a **survivor**, and it means
one of two things, both worth knowing:

* the behaviour is not tested - write the test; or
* the line does not matter - take it out.

    python tools/mutate.py --list
    python tools/mutate.py                 # every mutation in the set
    python tools/mutate.py -k manual       # just the ones named `manual*`

The original file is put back in a `finally`, so an interrupted run does not
leave a mutant behind. **Do not kill this process with `pkill`** - that skips
the restore, and everything measured afterwards is measured against a mutant.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# `tools/` sits inside the package, so one level up IS the package - the
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
T_NAME = ["tests/test_one_name_one_spelling.py",
          "tests/test_the_story_switches.py"]
T_DASH2 = ["tests/test_em_dash_source.py",
           "tests/test_one_name_one_spelling.py"]
T_MARKS = ["tests/test_a_box_of_nothing_but_marks.py",
           "tests/test_what_is_on_the_paper.py"]
T_KEYS = ["tests/test_one_key_per_service.py"]
T_BAR = ["tests/test_the_bar_holds_its_width.py"]
T_WORD = ["tests/test_the_word_is_typesetting.py"]

# The landing page. `T_SITE` is the CONTENT test only - not the one that asks
# whether index.html has been rebuilt, which every mutation here would trip
# for the same uninteresting reason and which would make the whole set say
# nothing. See `tests/test_the_website_is_built.py` for why they are apart.
SITE = "site/build.py"
T_SITE = ["tests/test_the_website.py"]
T_STORY = ["tests/test_the_story_switches.py"]
T_TRIM = ["tests/test_a_menu_you_can_trust.py", "tests/test_per_step_models.py",
          "tests/test_model_gone.py"]
T_MANUAL = ["tests/test_translating_it_yourself.py"]

# The hand-run seeding script. Not executed by any test - it wants a
# Firestore - so what is held is its source, and the property held is an
# ordering: refuse before you write.
SEED = "firebase/functions/seed.js"
T_SEED = ["tests/test_the_website.py"]

# The four pages a customer sees, and the numbers on them. `T_LOOK` runs the
# browser file as well as the source one: half of what matters here is only
# true once a browser has painted it.
# NOT `ACC` -- that is account.py, defined above, and naming both the same
# thing silently repointed every `acct-` mutant at the website. One of them
# reported SKIP, which is a mutant that measured nothing; the rest were
# quietly measuring the wrong file.
ACCHTML = "site/account.html"
SCSS = "site/style.css"
APPJS = "site/app.js"
COSTS = "site/costs.js"
T_LOOK = ["tests/test_the_site_pages.py", "tests/test_the_website.py"]

# A request that went quiet. The one failure the retry loop did not retry.
T_SLOW = ["tests/test_when_the_answer_never_comes.py"]

# The card that goes at the end of a chapter.
# Two things said in one balloon: which is spoken first, and whether they are
# one sentence. Both travel: the order is what the reader is handed and what a
# linked sentence is split across.
BALL = "detect/balloon.py"
T_WALL = ["tests/test_a_wall_of_sharp_change.py",
          "tests/test_black_bubbles.py"]
T_NAMEBOX = ["tests/test_the_balloon_may_name_the_box.py",
             "tests/test_black_bubbles.py"]
T_BALL = ["tests/test_two_things_in_one_balloon.py",
          "tests/test_one_box_per_bubble.py"]
CTD = "detect/comictext.py"

# The Typesetting panel and the page holding two different answers about one
# block, and the block flipping between them on every touch.
FR = "static/js/frames.js"
TSE = "static/js/typesetting-edit.js"
T_SPRING = ["tests/test_the_block_that_springs_back.py"]

# The strip re-cut, and the two File-tab words beside it.
IO = "static/js/project-io.js"
T_STRIP = ["tests/test_the_strip_is_not_a_page.py"]

# The knife: cutting a page in two by hand and joining two back into one,
# and where the strip settings live.
T_CUT = ["tests/test_cutting_a_page_by_hand.py"]
JS_CUT = "static/js/pagecut.js"
# (`CTD` is defined above.)
RO = "static/js/region-ops.js"
T_TUNE = ["tests/test_find_text_is_tuned_per_format.py"]
# One piece of writing, one box - the join, the empty-box sweep and the pair
# of passes with two answers about one piece of ink; and paper is not a
# balloon, which is the same message from lee and a different mechanism.
BALLN = "detect/balloon.py"
T_ONEBOX = ["tests/test_one_piece_of_writing_one_box.py",
            "tests/test_comic_text_detector.py",
            "tests/test_find_text_is_tuned_per_format.py"]
T_TOGETHER = ["tests/test_one_piece_of_writing_one_box.py"]
T_ALONE = ["tests/test_a_box_only_craft_saw.py",
           "tests/test_one_piece_of_writing_one_box.py"]
CRA = "detect/craft.py"
PJ = "static/js/project.js"
FR2 = "static/js/frames.js"
RND = "render.py"
T_FOLLOW = ["tests/test_pipeline.py"]
T_NOGBOX = ["tests/test_pipeline.py", "tests/test_box_sheet.py"]
T_CAGED = ["tests/test_one_piece_of_writing_one_box.py"]
T_FIVE = ["tests/test_one_piece_of_writing_one_box.py"]
T_HOLDS = ["tests/test_a_second_pair_of_eyes.py"]
T_OWNTEXT = ["tests/test_one_piece_of_writing_one_box.py",
             "tests/test_find_text_is_tuned_per_format.py"]
T_CHARS = ["tests/test_one_piece_of_writing_one_box.py",
           "tests/test_find_text_is_tuned_per_format.py"]
T_PAPERBALL = ["tests/test_one_piece_of_writing_one_box.py",
               "tests/test_the_sky_is_not_a_balloon.py",
               "tests/test_a_wall_of_sharp_change.py"]
T_DRAWN = ["tests/test_too_empty_to_be_type.py",
           "tests/test_find_text_is_tuned_per_format.py"]
T_SKY = ["tests/test_the_sky_is_not_a_balloon.py",
         "tests/test_find_text_is_tuned_per_format.py"]
T_COVER = ["tests/test_the_writing_the_block_head_missed.py",
           "tests/test_find_text_is_tuned_per_format.py"]
T_LOBES = ["tests/test_two_lobes_two_boxes.py",
           "tests/test_find_text_is_tuned_per_format.py"]
T_CROP = ["tests/test_a_crop_per_box.py"]
T_BADREPLY = ["tests/test_one_bad_reply_is_not_the_chapter.py",
              "tests/test_a_crop_per_box.py"]
T_PAPER = ["tests/test_what_is_on_the_paper.py",
           "tests/test_no_pause_the_page_never_drew.py"]
T_INK = ["tests/test_what_colour_the_letters_are.py"]
T_LOBESAY = ["tests/test_two_sentences_in_one_balloon.py",
             "tests/test_two_lobes_two_boxes.py"]
T_SAID = ["tests/test_one_person_one_name.py"]
T_FIT = ["tests/test_the_line_has_to_fit.py",
         "tests/test_no_pause_the_page_never_drew.py"]
T_HOLD = ["tests/test_the_line_the_page_can_hold.py"]
T_SIZE = ["tests/test_the_size_the_reader_gets.py",
          "tests/test_em_dash_source.py"]
T_BAYS = ["tests/test_no_bays_in_the_writing.py"]
T_DRAW = ["tests/test_asking_the_model_to_draw_it_again.py",
          "tests/test_the_sfx_gets_cleaned.py",
          "tests/test_which_box_was_cleaned_how.py"]
T_SLAB = ["tests/test_a_balloon_you_can_see_through.py",
          "tests/test_clean_routing.py"]
T_GRAIN = ["tests/test_a_second_pass_for_the_hard_spots.py",
           "tests/test_clean_says_when_it_fails.py"]
T_ONLY = ["tests/test_only_the_text_and_only_inside.py"]
T_DREW = ["tests/test_a_sound_effect_you_just_drew.py"]
T_TURN = ["tests/test_a_box_you_turned.py"]
IN = "inpaint.py"
T_FRONT = ["tests/test_nothing_in_front_of_the_line.py",
           "tests/test_em_dash_source.py"]
T_SAYS = ["tests/test_the_cleaner_says_what_it_did.py",
          "tests/test_which_box_was_cleaned_how.py"]
T_PURSE = ["tests/test_a_purse_you_can_top_up.py"]
INK = "inkstyle.py"
T_GROW = ["tests/test_the_whole_run_of_writing.py",
          "tests/test_the_box_covers_the_whole_effect.py"]
T_HANDSFX = ["tests/test_a_sound_effect_box_by_hand.py"]
T_TALL = ["tests/test_a_page_too_long_to_read.py"]
T_SFXTICK = ["tests/test_the_sound_effect_tick_is_live.py"]
T_TWOFX = ["tests/test_two_effects_in_one_box.py"]
CRF = "detect/craft.py"
ED = "editor.py"
AID = "detect/aidetect.py"
T_FAST = ["tests/test_find_text_is_faster.py"]
T_FRAME = ["tests/test_centred_pages.py"]
T_REAL = ["tests/test_is_the_ai_really_finding_it.py"]
T_AI = ["tests/test_ai_boxes.py"]
T_EDGE = ["tests/test_a_black_page_still_looks_like_a_page.py"]
T_TOK = ["tests/test_a_refused_token_is_said_once.py"]
T_EYES = ["tests/test_a_second_pair_of_eyes.py"]
T_FAM = ["tests/test_box_type_families.py"]
JS_VW = "static/js/view.js"
T_WEB = ["tests/test_the_strip_settings_belong_to_webtoons.py"]
T_LAST = ["tests/test_the_chapter_before_this_one.py"]
JS_IO = "static/js/project-io.js"
JS_PJ = "static/js/project.js"
HTM = "static/editor.html"
PRJ_PY = "project.py"
T_RAIL = ["tests/test_the_rail_and_the_story_you_type.py"]
INP = "inpaint.py"
MOD = "models.py"
T_FOCUSGONE = ["tests/test_a_second_pass_for_the_hard_spots.py",
               "tests/test_clean_routing.py"]
# 93% of Find text is one net, and the layout its weights are stored in is the
# only saving that leaves every box where it was.
T_CPUFAST = ["tests/test_craft_gets_the_cpus_fast_path.py",
             "tests/test_a_second_pair_of_eyes.py",
             "tests/test_a_box_only_craft_saw.py"]
# The emptiest box of all, which the sweep for empty boxes used to exempt.
T_NOTHING = ["tests/test_a_box_with_nothing_in_it.py",
             "tests/test_one_piece_of_writing_one_box.py",
             "tests/test_find_text_is_tuned_per_format.py"]
# A box the reader found nothing in.
ED_PY = "editor.py"
T_BLANK = ["tests/test_a_box_the_reader_found_nothing_in.py"]
# Untick Sound effect and the second detector should not run.
T_NOFX = ["tests/test_no_effects_no_craft.py",
          "tests/test_find_text_is_tuned_per_format.py"]
# A balloon whatever colour it is.
CBU = "detect/comicbubble.py"
T_COLOUR = ["tests/test_a_balloon_of_any_colour.py"]
# Painted lettering is not dialogue.
T_PAINT = ["tests/test_painted_lettering_is_not_dialogue.py"]
DBCOO = "detect/dbcoo.py"
T_BODIES = ["tests/test_the_artwork_has_to_show_its_letters.py"]
T_WELD = ["tests/test_the_balloon_outranks_the_specialist.py",
          "tests/test_two_specialists_in_the_settings.py"]
SEG = "detect/mangaseg.py"
T_SEG = ["tests/test_the_manga109_segmenter.py"]
ANIM = "detect/animetext.py"
T_ANIM = ["tests/test_one_detector_finds_all_of_it.py"]
NOTICE = "NOTICE"
T_LIC = ["tests/test_the_licence_is_stated.py"]
RK = "readkinds.py"
T_RK = ["tests/test_the_box_is_named_from_what_was_read.py"]
STOPM = "stopping.py"
BOXSEL = "static/js/boxselect.js"
T_STOP = ["tests/test_stop_means_stop.py"]
ROPS = "static/js/region-ops.js"
PANELS = "static/js/panels.js"
SELJS = "static/js/select.js"

CARD = "tools/adcard.py"
T_CARD = ["tests/test_the_card_at_the_end.py"]

# A chapter named in Korean, and a page that is not there any more.
IMG = "imgio.py"
T_KOREAN = ["tests/test_a_korean_filename_is_a_filename.py"]
T_GONE = ["tests/test_a_page_that_is_not_there.py"]

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
    ("substitutes-on-in-the-library-default", "typeset.py",
     "\n    substitutes: bool = False\n",
     "\n    substitutes: bool = True\n", T_FONT),
    ("settings-default-substitutes-off", "project.py",
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
    ("sanitise-substitutes-always", "typeset.py",
     "    cov = _font_coverage(font_path) if font_path and substitutes else None",
     "    cov = _font_coverage(font_path) if font_path else None", T_FONT),
    ("no-flag-when-a-glyph-is-missing", "typeset.py",
     '        if missing:\n            region.flagged = ',
     '        if False:\n            region.flagged = ', T_FONT),
    ("cfg-ignores-the-setting", PY,
     'substitutes=bool(s.get("substitutes"))', "substitutes=True", T_FONT),

    # ---- outside text and sfx running past the box (2026-08-04)
    ("spill-never-happens", "typeset.py",
     '    if _kinds.family_of(region.kind) == "freefloat":\n'
     '        lay = _spill_fit(text, m, cfg)',
     '    if False:\n        lay = _spill_fit(text, m, cfg)', T_SPILL),
    ("spill-for-bubbles-too", "typeset.py",
     '    if _kinds.family_of(region.kind) == "freefloat":',
     '    if True:', T_SPILL),
    ("spill-below-the-minimum", "typeset.py",
     "    path, size = cfg.font_path, cfg.min_font",
     "    path, size = cfg.font_path, cfg.absolute_floor", T_SPILL),
    ("spill-not-marked", "typeset.py",
     "                      fit_ok=True, spills=True)",
     "                      fit_ok=True, spills=False)", T_SPILL),
    ("spill-hung-off-the-corner", "typeset.py",
     "    cx, cy = bx + bw / 2.0, by + bh / 2.0\n"
     "    top = cy - len(lines) * lh / 2.0",
     "    cx, cy = bx, by\n    top = cy - len(lines) * lh / 2.0", T_SPILL),
    ("sfx-sweep-goes-under-the-minimum", "typeset.py",
     "    lay = fit_sfx(frame, text, measure, lo=cfg.min_font, hi=160)",
     "    lay = fit_sfx(frame, text, measure, lo=cfg.absolute_floor, hi=160)",
     T_SPILL),
    ("clamp-shrinks-past-the-minimum", "typeset.py",
     "    floor = cfg.min_font\n    want = int(lay.font_size * scale)",
     "    floor = cfg.absolute_floor\n    want = int(lay.font_size * scale)",
     T_SPILL),
    ("clamp-grows-a-tiny-effect", "typeset.py",
     "    if size >= lay.font_size:\n        return lay",
     "    if False:\n        return lay", T_SPILL),
    ("spilling-block-is-clamped-into-its-region", "typeset.py",
     '    if getattr(lay, "spills", False):\n        return lay',
     "    if False:\n        return lay", T_SPILL),
    ("render-clips-the-spill-back-to-the-box", "render.py",
     "        free = free or bool(getattr(lay, \"spills\", False))",
     "        free = free or False", T_SPILL),
    ("render-clips-nothing-at-all", "render.py",
     "        free = free or bool(getattr(lay, \"spills\", False))",
     "        free = True", T_SPILL),
    ("spill-runs-off-the-page", "typeset.py",
     "            if r.layout and getattr(r.layout, \"spills\", False):\n"
     "                r.layout = keep_on_page(r.layout, cfg, page.image.shape)",
     "            if False:\n"
     "                r.layout = keep_on_page(r.layout, cfg, page.image.shape)",
     T_SPILL),
    ("keep-on-page-runs-before-the-frame-is-settled", "typeset.py",
     "                r.layout = anchor_to_frame(r.layout, cfg)\n"
     "            # Out of the box is allowed; off the page is not. AFTER",
     "                pass\n"
     "            # Out of the box is allowed; off the page is not. AFTER",
     T_SPILL),
    ("keep-on-page-shoves-a-block-wider-than-the-page", "typeset.py",
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
    ("two-brushes-back-on-the-toolbar", "static/js/toolbar.js",
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
    ("strip-first-gutter-past-the-target", STR,
     "            cuts.append(int(near[np.argmin(abs(near - (at + target)))]))",
     "            cuts.append(int(near[np.argmax(near >= at + target)]))",
     T_STRIP),
    ("strip-first-gutter-in-the-window", STR,
     "            cuts.append(int(near[np.argmin(abs(near - (at + target)))]))",
     "            cuts.append(int(near[0]))", T_STRIP),
    ("strip-a-page-is-cut-short-of-the-gap-again", STR,
     "        if not len(after):\n"
     "            break                  # none left: everything below here is one page\n"
     "        cuts.append(int(after[0]))\n",
     "        if not len(after) or after[0] - at > ceiling:\n"
     "            break\n"
     "        cuts.append(int(after[0]))\n", T_STRIP),
    ("strip-running-over-is-not-reported", STR,
     "        if after[0] - at > ceiling:\n            over.append(int(after[0]))",
     "        if False:\n            over.append(int(after[0]))", T_STRIP),
    ("strip-a-chapter-left-in-one-piece-passes-silently", STR,
     "    if len(cuts) > 1 and H - cuts[-2] > ceiling:\n        over.append(H)\n",
     "", T_STRIP),
    ("strip-page-height-setting-ignored", PRJ,
     '        tall = float(self.settings.get("strip_tall") or 0) or 3.5',
     "        tall = 3.5", T_STRIP),
    ("strip-ceiling-setting-ignored", PRJ,
     '        top = float(self.settings.get("strip_tall_max") or 0) or 8.5',
     "        top = 8.5", T_STRIP),
    ("strip-the-height-is-not-scaled-by-the-width", PRJ,
     "        return max(600, int(round(w * tall))), max(1000, int(round(w * top)))",
     "        return max(600, int(round(tall))), max(1000, int(round(top)))",
     T_STRIP),
    ("strip-a-ceiling-under-the-target-is-taken-literally", PRJ,
     "        top = max(top, tall)\n", "", T_STRIP),
    ("strip-a-page-of-no-width-is-measured-from", PRJ,
     "        for pg in self.pages:\n            if pg.width:\n"
     "                return int(pg.width)",
     "        for pg in self.pages:\n            if True:\n"
     "                return int(pg.width)", T_STRIP),
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
    ("box-reader-not-told-the-closer-fit-wins", TR,
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
    ("box-reader-not-told-about-slanted-outlines", "translate.py",
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
    # nought was read as "well, this page's worth", and a full-chapter run -
    # which sends NO context - was quoted a hundred thousand tokens it never
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
     "    dout = _clamp(rout / pout) if pout and rout else 1.0\n"
     "    return (din, dout, dout)",
     "    dout = _clamp(rout / pout) if pout and rout else 2.0\n"
     "    return (din, dout, dout)", T_LEARN),
    ("learn-the-correction-is-never-applied", COIN,
     "    din, dout, dthk = drift(step, model, backend)",
     "    din, dout, dthk = 1.0, 1.0, 1.0", T_LEARN),
    ("learn-the-thinking-correction-lands-on-the-reply", COIN,
     "    return r.usd(tin=tin * din, cached=cached * din,\n"
     "                 tout=tvis * dout + tthk * dthk)",
     "    return r.usd(tin=tin * din, cached=cached * din,\n"
     "                 tout=(tvis + tthk) * dout)", T_LEARN),
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
    # (re-anchored: the meter line grew src/detail/labelled after these were
    # written, so both anchors had gone stale and the pair sat SKIPped)
    ("learn-the-meter-does-not-say-how-big-the-run-was", PY,
     "                               boxes=sum(boxes[:done]), pages=done,",
     "                               boxes=0, pages=0,", T_LEARN),
    ("learn-a-cancelled-run-claims-every-page", PY,
     "                               boxes=sum(boxes[:done]), pages=done,",
     "                               boxes=sum(boxes), pages=len(boxes),",
     T_LEARN),

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
    # ---- the re-cut that is only for strips
    ("strip-a-manga-chapter-is-re-cut-too", PRJ,
     "        if not force and not STRIP_MEDIA.intersection({self.medium}):\n"
     "            return {}\n", "", T_STRIP),
    ("strip-manga-is-quietly-included", PRJ,
     'STRIP_MEDIA = {"manhwa", "manhua"}',
     'STRIP_MEDIA = {"manhwa", "manhua", "manga"}', T_STRIP),
    ("strip-manhua-is-quietly-dropped", PRJ,
     'STRIP_MEDIA = {"manhwa", "manhua"}', 'STRIP_MEDIA = {"manhwa"}', T_STRIP),
    ("strip-manhwa-is-quietly-dropped", PRJ,
     'STRIP_MEDIA = {"manhwa", "manhua"}', 'STRIP_MEDIA = {"manhua"}', T_STRIP),
    ("strip-nothing-is-ever-re-cut", PRJ,
     'STRIP_MEDIA = {"manhwa", "manhua"}', 'STRIP_MEDIA = set()', T_STRIP),
    ("strip-asking-by-hand-is-refused-as-well", PRJ,
     "        if not force and not STRIP_MEDIA.intersection({self.medium}):",
     "        if not STRIP_MEDIA.intersection({self.medium}):", T_STRIP),
    # ---- a chapter named in Korean
    ("korean-the-flags-are-dropped", IMG,
     "        return cv2.imdecode(np.frombuffer(data, np.uint8), flags)",
     "        return cv2.imdecode(np.frombuffer(data, np.uint8))", T_KOREAN),
    ("korean-a-missing-file-raises-instead-of-answering-None", IMG,
     "    try:\n        with open(path, \"rb\") as fh:\n"
     "            data = fh.read()\n    except OSError:\n        return None\n",
     "    with open(path, \"rb\") as fh:\n        data = fh.read()\n", T_KOREAN),
    ("korean-a-decoder-that-throws-takes-the-run-with-it", IMG,
     "    try:\n        return cv2.imdecode(np.frombuffer(data, np.uint8),"
     " flags)\n",
     "    if True:\n        return cv2.imdecode(np.frombuffer(data,"
     " np.uint8), flags)\n", T_KOREAN),
    ("korean-an-encoder-that-throws-takes-the-run-with-it", IMG,
     "    try:\n        ok, buf = cv2.imencode(ext, img, params or [])\n"
     "    except cv2.error:\n        return False\n",
     "    ok, buf = cv2.imencode(ext, img, params or [])\n", T_KOREAN),
    ("korean-the-write-always-claims-it-worked", IMG,
     "    try:\n        with open(path, \"wb\") as fh:\n"
     "            fh.write(buf.tobytes())\n    except OSError:\n"
     "        return False\n    return True\n",
     "    try:\n        with open(path, \"wb\") as fh:\n"
     "            fh.write(buf.tobytes())\n    except OSError:\n"
     "        pass\n    return True\n", T_KOREAN),
    ("korean-every-write-is-a-png-whatever-it-is-called", IMG,
     '    ext = os.path.splitext(path)[1] or ".png"',
     '    ext = ".png"', T_KOREAN),
    ("korean-an-upload-is-checked-with-imread-again", PRJ,
     "        img = imgio.imread(dest)\n        if img is None:",
     "        img = cv2.imread(dest)\n        if img is None:", T_KOREAN),
    ("korean-a-rescan-measures-with-imread-again", PRJ,
     "            img = imgio.imread(p)\n"
     "            h, w = (img.shape[:2] if img is not None else (0, 0))",
     "            img = cv2.imread(p)\n"
     "            h, w = (img.shape[:2] if img is not None else (0, 0))",
     T_KOREAN),
    ("korean-the-strip-profile-reads-with-imread-again", "strip.py",
     "    g = imgio.imread(path, cv2.IMREAD_GRAYSCALE)\n    if g is None:\n"
     "        return np.zeros((0, 3), np.float32)",
     "    g = cv2.imread(path, cv2.IMREAD_GRAYSCALE)\n    if g is None:\n"
     "        return np.zeros((0, 3), np.float32)", T_KOREAN),

    # ---- a page that is not there any more
    ("gone-a-missing-page-is-a-traceback-again", PY,
     "            gone = self._no_such_page(p, path)\n"
     "            if gone:\n"
     "                return self._json({\"error\": gone}, 404)\n"
     "            if path in (\"/\", \"/index.html\"):",
     "            if path in (\"/\", \"/index.html\"):", T_GONE),
    ("gone-a-post-to-a-missing-page-still-runs", PY,
     "            gone = self._no_such_page(p, path)\n"
     "            if gone:\n"
     "                return self._json({\"error\": gone}, 404)\n"
     "            if path == \"/api/project_upload\":",
     "            if path == \"/api/project_upload\":", T_GONE),
    ("gone-a-delete-on-a-missing-page-still-runs", PY,
     "        gone = self._no_such_page(p, path)\n        if gone:\n"
     "            return self._json({\"error\": gone}, 404)\n\n"
     "        m = re.fullmatch(r\"/api/page/(\\d+)\", path)",
     "        m = re.fullmatch(r\"/api/page/(\\d+)\", path)", T_GONE),
    ("gone-the-last-page-is-called-missing", PY,
     "        if 0 <= i < len(p.pages):", "        if 0 <= i < len(p.pages) - 1:",
     T_GONE),
    ("gone-the-message-does-not-say-which-page", PY,
     'return (f"page {i + 1} is not in this project any more "\n'
     '                f"(there are {len(p.pages)})")',
     'return "page missing"', T_GONE),
    ("gone-a-region-number-is-read-as-the-page", PY,
     '    _NUMBERED = re.compile(r"/(?:api/page|img|render)/(\\d+)(?:/.*)?")',
     '    _NUMBERED = re.compile(r"/(?:api/page|img|render)/.*?(\\d+)$")',
     T_GONE),
    # ---- the chapter before this one, and the numbering
    ("last-the-upload-folder-is-never-emptied", PY,
     "                p.put_the_last_chapter_away()\n", "", T_LAST),
    ("last-the-old-files-are-deleted-not-kept", PRJ,
     "        prev = os.path.join(self.output_dir, \"input-previous\")\n"
     "        shutil.rmtree(prev, ignore_errors=True)\n"
     "        try:\n            shutil.move(d, prev)\n",
     "        prev = os.path.join(self.output_dir, \"input-previous\")\n"
     "        try:\n            shutil.rmtree(d)\n", T_LAST),
    ("last-every-generation-is-kept-for-ever", PRJ,
     "        shutil.rmtree(prev, ignore_errors=True)\n        try:",
     "        try:", T_LAST),
    ("last-an-empty-folder-is-still-moved-aside", PRJ,
     "        if not os.path.isdir(d) or not os.listdir(d):\n            return 0",
     "        if not os.path.isdir(d):\n            return 0", T_LAST),
    ("last-the-new-folder-is-not-made-again", PRJ,
     "        os.makedirs(d, exist_ok=True)\n"
     "        return sum(len(f) for _r, _dirs, f in os.walk(prev))",
     "        return sum(len(f) for _r, _dirs, f in os.walk(prev))", T_LAST),
    ("num-a-split-does-not-renumber", PRJ,
     "        # `012a` and `012b` sort where `012` sorted, which is right and is also\n"
     "        # how a chapter ends up called 011, 012a, 012b, 013. lee asked for the\n"
     "        # numbering to be put straight, and only ever from here.\n"
     "        self.renumber_pages()\n", "", T_LAST),
    ("num-a-join-does-not-renumber", PRJ,
     "        self._img_cache.clear()\n        self.save()\n"
     "        self.renumber_pages()\n        return True, \"\"\n\n    def remove_page",
     "        self._img_cache.clear()\n        self.save()\n"
     "        return True, \"\"\n\n    def remove_page", T_LAST),
    ("num-the-numbering-starts-at-nought", PRJ,
     "        for n, pg in enumerate(self.pages, 1):",
     "        for n, pg in enumerate(self.pages):", T_LAST),
    ("num-every-page-keeps-a-png-extension", PRJ,
     "            ext = os.path.splitext(pg.path)[1] or \".png\"\n"
     "            want = os.path.join(os.path.dirname(pg.path), f\"{n:03d}{ext}\")",
     "            ext = \".png\"\n"
     "            want = os.path.join(os.path.dirname(pg.path), f\"{n:03d}{ext}\")",
     T_LAST),
    ("num-renaming-goes-straight-over-a-name-in-use", PRJ,
     "            tmp = os.path.join(os.path.dirname(pg.path), f\".renum{k}.tmp\")",
     "            tmp = want", T_LAST),
    ("num-the-page-keeps-pointing-at-the-old-file", PRJ,
     "            pg.path = want\n            pg.name = os.path.basename(want)",
     "            pg.name = os.path.basename(want)", T_LAST),
    ("num-the-rescan-renumbers-too", PRJ,
     "        known = {p.path: p for p in self.pages}",
     "        self.renumber_pages()\n"
     "        known = {p.path: p for p in self.pages}", T_LAST),
    # ---- the sound-effect tick, live again on every format
    #
    # The nine `sfxoff-` mutants that were here all defended the OVERRIDE -
    # `NO_SFX_MEDIA`, `detectable_kinds`, `sfxIsDetectable`, the Coming soon
    # pill. Every one of them mutated code that no longer exists. They are
    # replaced rather than deleted: the same defence, pointed at the thing
    # that carries the decision now, which is the tick and `only_kinds`.
    ("sfxtick-the-format-gets-a-vote-again", PRJ,
     '        kinds = list(kinds or ["bubble"])',
     '        kinds = [k for k in (kinds or ["bubble"])\n'
     '                 if k != "sfx" or self.medium == "manga"]', T_SFXTICK),
    ("sfxtick-the-tick-stops-being-what-decides", PRJ,
     "    want = {k for k in (kinds or []) if k in _kinds.FAMILIES}\n"
     "    if not want:\n"
     "        return found",
     "    want = {k for k in (kinds or []) if k in _kinds.FAMILIES}\n"
     "    if True:\n"
     "        return found", T_SFXTICK),
    ("sfxtick-the-row-starts-ticked", HTM,
     '      <label class="optrow"><input type="checkbox" id="kSfx"',
     '      <label class="optrow"><input type="checkbox" id="kSfx" checked',
     T_SFXTICK),
    ("sfxtick-the-sub-options-never-appear", JS,
     "  if(box) box.style.display = on ? '' : 'none';",
     "  if(box) box.style.display = 'none';", T_SFXTICK),
    ("sfxtick-the-sub-options-are-always-there", JS,
     "  if(box) box.style.display = on ? '' : 'none';",
     "  if(box) box.style.display = '';", T_SFXTICK),
    ("sfxtick-ticking-it-asks-for-nothing", JS,
     "  if($('kSfx').checked)    k.push('sfx');",
     "  if(false)                k.push('sfx');", T_SFXTICK),
    # AFTER the loop that clears `disabled` on all three, not before it -
    # before it, the loop undoes the mutation and the mutant measures nothing.
    ("sfxtick-the-row-is-greyed-out-again", JS,
     "  // The three ticks are alike, on every format.",
     "  const _s=$('kSfx');\n"
     "  if(_s){ _s.checked=false; _s.disabled=true;\n"
     "          _s.closest('label').classList.add('disabled'); }\n"
     "  // The three ticks are alike, on every format.", T_SFXTICK),
    ("sfxtick-the-coming-soon-pill-comes-back", HTM,
     "        <span><b>Sound effects</b>",
     '      <span><b>Sound effects</b><span id="kSfxSoon" class="pill">'
     "Coming soon</span><br>", T_SFXTICK),
    # `sfxtick-nobody-is-told-they-can-draw-one` stood here. The row no
    # longer says how to draw one by hand: lee asked for the whole box to
    # be *"just be ine or 2 line"*, and that sentence was the third.
    # ---- a wall of sharp change, closed and roundish
    ("wall-the-rule-is-not-there-at-all", BALL,
     "    _shut_in_a_round_wall(gray, regions, cfg)\n", "", T_WALL),
    ("wall-the-canny-bar-is-the-strict-one-again", BALL,
     "WALL_LO, WALL_HI = 30, 90", "WALL_LO, WALL_HI = 60, 150", T_WALL),
    ("wall-the-seal-does-not-close-fur", BALL,
     "WALL_SEAL = 15", "WALL_SEAL = 1", T_WALL),
    ("wall-one-pixel-thin-so-the-fill-leaks", BALL,
     "    e = cv2.dilate(e, np.ones((3, 3), np.uint8))\n", "", T_WALL),
    ("wall-anything-shut-counts-however-shapeless", BALL,
     "WALL_CIRC = 0.50", "WALL_CIRC = 0.0", T_WALL),
    ("wall-it-need-not-be-an-ellipse", BALL,
     "WALL_FIT = 0.85", "WALL_FIT = 0.0", T_WALL),
    ("wall-the-hole-it-punched-counts-as-a-balloon", BALL,
     "    if a < WALL_SLACK * hole or len(c) < 5:",
     "    if len(c) < 5:", T_WALL),
    ("wall-a-shape-you-can-walk-out-of-counts", BALL,
     "    if (comp[0].any() or comp[-1].any() or comp[:, 0].any()\n"
     "            or comp[:, -1].any()):\n        return False\n", "", T_WALL),
    ("wall-the-writing-is-left-in-the-edge-map", BALL,
     "    e[ey0:ey1, ex0:ex1] = 0\n", "", T_WALL),
    ("wall-it-renames-sound-effects-too", BALL,
     '        if r.kind != "freefloat" or r.bubble_mask is not None:',
     "        if r.bubble_mask is not None:", T_WALL),
    # ---- The balloon it is in may say what it is
    ("namebox-the-free-blocks-are-not-searched-upright", BALL,
     '    up = _attach(gray, regions, cfg, ("bubble", "narration", "freefloat"),\n'
     '                 promote=True)',
     '    up = _attach(gray, regions, cfg, ("bubble", "narration"))', T_NAMEBOX),
    ("namebox-found-but-not-renamed", BALL,
     '    up = _attach(gray, regions, cfg, ("bubble", "narration", "freefloat"),\n'
     '                 promote=True)',
     '    up = _attach(gray, regions, cfg, ("bubble", "narration", "freefloat"))',
     T_NAMEBOX),
    ("namebox-a-caption-is-renamed-too", BALL,
     '            if r.kind == "freefloat" and r.bubble_mask is not None:',
     "            if r.bubble_mask is not None:", T_NAMEBOX),
    ("namebox-renamed-without-finding-anything", BALL,
     '            if r.kind == "freefloat" and r.bubble_mask is not None:',
     '            if r.kind == "freefloat":', T_NAMEBOX),
    ("namebox-the-page-is-labelled-twice", BALL,
     "    if not todo:\n        return 0\n\n    n, labels = _free_labels(gray, cfg)",
     "    if not todo:\n        return 0\n\n    _free_labels(gray, cfg)\n"
     "    n, labels = _free_labels(gray, cfg)",
     T_NAMEBOX),
    # ---- A page too long for the 1024 letterbox
    ("tall-the-limit-is-not-the-measured-one", CTD,
     "TALL_ASPECT = 6.0", "TALL_ASPECT = 10.0", T_TALL),
    ("tall-it-warns-about-every-webtoon", CTD,
     "TALL_ASPECT = 6.0", "TALL_ASPECT = 2.0", T_TALL),
    ("tall-it-measures-the-height-and-not-the-shape", CTD,
     "    return bool(w) and bool(h) and (max(w, h) / float(min(w, h) or 1)\n"
     "                                    > TALL_ASPECT)",
     "    return bool(w) and bool(h) and h > 4140", T_TALL),
    ("tall-a-page-with-no-size-is-warned-about", CTD,
     "    return bool(w) and bool(h) and (max(w, h) / float(min(w, h) or 1)\n"
     "                                    > TALL_ASPECT)",
     "    return (max(w, h) / float(min(w, h) or 1) > TALL_ASPECT)", T_TALL),
    ("tall-the-browser-keeps-its-own-copy-of-the-limit", JS,
     "  const lim = (proj && proj.tall_aspect) || 0;",
     "  const lim = 6;", T_TALL),
    ("tall-the-warning-never-shows", JS,
     "  if(!tall.length){ el.style.display='none'; return; }",
     "  { el.style.display='none'; return; }", T_TALL),
    ("tall-the-warning-does-not-say-what-to-do", JS,
     "    + `shorter page. Cut / join, on the Translation view, splits a "
     "strip up. `",
     "    + `shorter page. `", T_TALL),
    ("tall-nobody-asks-the-question-before-a-run", JS,
     "  syncTallWarning();\n}", "}", T_TALL),
    # ---- Sound effects: off by default, and still pressable
    ("threekey-a-hidden-group-swallows-the-box", RO,
     "  const fam = (typeof familyOf==='function') ? familyOf(kind) : kind;\n"
     "  if((hiddenKinds||[]).includes(fam)){\n"
     "    await setKindShown(fam, true);\n"
     "    return;\n"
     "  }\n",
     "", T_HANDSFX),
    ("threekey-every-group-is-turned-back-on", RO,
     "  if((hiddenKinds||[]).includes(fam)){",
     "  if(true){", T_HANDSFX),
    ("threekey-three-is-not-the-sound-effect", "static/js/frames.js",
     "const KIND_FAMILIES=['bubble','freefloat','sfx'];",
     "const KIND_FAMILIES=['bubble','sfx','freefloat'];", T_HANDSFX),
    # ---- ...and a loose box may be a drawn effect rather than outside text
    ("sky-a-huge-hollow-shout-stays-dialogue", CTD,
     "            if effect_fill and \\\n"
     "                    _glyph_share(gray, r.bbox, r.text_mask) >= LOOSE_HUGE and \\\n"
     "                    _looks_hand_drawn(gray, r.bbox, r.text_mask, effect_fill):\n"
     "                r.kind = \"sfx\"\n"
     "                continue\n",
     "", T_SKY),
    ("sky-the-size-gate-is-gone-so-the-credits-go-too", CTD,
     "                    _glyph_share(gray, r.bbox, r.text_mask) >= LOOSE_HUGE and \\\n",
     "", T_SKY),
    ("sky-the-size-bar-is-not-the-measured-one", CTD,
     "LOOSE_HUGE = 0.15", "LOOSE_HUGE = 0.10", T_SKY),
    ("sky-the-size-is-measured-against-the-box", CTD,
     "    return float(np.median(hs)) / float(max(1, W))",
     "    return float(np.median(hs)) / float(max(1, x1 - x0))", T_SKY),
    # ---- a tall box of outside text is one drawn shape
    ("tallfx-the-tall-case-is-gone", CTD,
     "            if _looks_hand_drawn(gray, r.bbox, r.text_mask, effect_fill) or \\\n"
     "                    _taller_than_wide(r.bbox):",
     "            if _looks_hand_drawn(gray, r.bbox, r.text_mask, effect_fill):",
     T_DRAWN),
    ("tallfx-every-box-out-there-is-tall-enough", CTD,
     "TALL_EFFECT = 1.15", "TALL_EFFECT = 0.5", T_DRAWN),
    ("tallfx-the-shape-is-read-the-wrong-way-round", CTD,
     "    return bool(w) and h > TALL_EFFECT * w",
     "    return bool(h) and w > TALL_EFFECT * h", T_DRAWN),
    # ---- a crop per box instead of the page
    ("crop-scaled-by-the-crop-and-not-the-glyphs", "ocr.py",
     "        s = float(glyph_px) / _glyph_px(page, r)",
     "        s = float(glyph_px) / max(1, min(ch, cw) / 3.0)", T_CROP),
    ("crop-the-glyph-target-is-not-the-measured-one", "ocr.py",
     "BOX_GLYPH = 64", "BOX_GLYPH = 16", T_CROP),
    ("crop-there-is-no-padding-round-the-box", "ocr.py",
     "BOX_PAD = 0.25", "BOX_PAD = 0.0", T_CROP),
    ("crop-a-tiny-box-stays-tiny", "ocr.py",
     "        s = max(s, BOX_MIN / max(1, max(cw, ch)))", "", T_CROP),
    # (No mutant for the max_side clamp inside the scale. Taking it out
    #  changes no output: `_encode` clamps to the same number on the way to
    #  PNG. It is there so a 12x scale-up is not allocated and then thrown
    #  away, which is a speed and memory guard rather than a behaviour, and an
    #  equivalent mutant is not a hole in the tests.)
    ("crop-the-setting-does-not-reach-it", "ocr.py",
     '        return page_box_crops(page, max_side=max_side)\n',
     "        pass\n", T_CROP),
    ("crop-the-crops-are-not-in-reading-order", "ocr.py",
     '    for r in sorted(regions, key=lambda r: (getattr(r, "order", 0), r.id)):',
     "    for r in regions:", T_CROP),
    ("crop-every-picture-is-its-own-turn-again", TR,
     "    n_batch = max(1, int(batch or 1))", "    n_batch = 1", T_CROP),
    ("crop-the-reader-is-not-told-which-image-is-which", TR,
     '        if len(group) > 1:\n', "        if False:\n", T_CROP),
    # ---- the reader copies the page, it does not tidy it
    ("paper-the-ellipsis-is-rewritten-again", TR,
     '        "- Copy the punctuation EXACTLY as printed, character for character: "',
     '        "- Write an ellipsis as three periods ... "', T_PAPER),
    ("paper-the-stop-after-an-ellipsis-is-not-named", TR,
     '"a full stop after an ellipsis (….) is part of the line, and a "',
     '"and a "', T_PAPER),
    ("paper-the-long-vowel-mark-is-dropped-in-the-edit", TR,
     '"long-vowel mark is ー. Do not tidy, normalise, or add stray symbols.\\n"',
     '"Do not tidy, normalise, or add stray symbols.\\n"', T_PAPER),
    ("paper-nobody-asks-for-the-line-breaks", TR,
     '        "- Keep the LINE BREAKS as printed. A run of writing set as three lines "\n'
     '        "comes back as three lines separated by \\\\n, broken in the same places. "\n'
     '        "Do not re-wrap it, and do not join it into one line.\\n"',
     '        ""', T_PAPER),
    ("paper-re-wrapping-is-allowed", TR,
     '"Do not re-wrap it, and do not join it into one line.\\n"',
     '"Do not join it into one line.\\n"', T_PAPER),
    ("paper-the-english-loses-its-three-periods", TR,
     "  straight apostrophes and quotes, three periods for an ellipsis, and a",
     "  straight apostrophes and quotes, an ellipsis, and a", T_PAPER),
    # ---- a double balloon is one balloon, not one sentence
    ("say-a-balloon-goes-as-a-sentence-link", TR,
     '                **({("balloon"\n'
     '                     if getattr(r, "link_kind", "") == "balloon" else "link"):\n'
     '                    int(r.link)} if getattr(r, "link", 0) else {}),',
     '                **({"link": int(r.link)} if getattr(r, "link", 0) else {}),',
     T_LOBESAY),
    ("say-an-old-link-with-no-kind-becomes-a-balloon", TR,
     'if getattr(r, "link_kind", "") == "balloon" else "link"',
     'if getattr(r, "link_kind", "") != "sentence" else "link"', T_LOBESAY),
    ("say-the-lobes-are-not-marked-as-lobes", "detect/balloon.py",
     '            lobes[i][0].link_kind = "balloon"', "            pass",
     T_LOBESAY),
    ("say-reads-on-does-not-mark-its-own", TR,
     '            r.link_kind = "sentence" if joined else ""', "            pass",
     T_LOBESAY),
    ("say-unlinking-leaves-the-kind-behind", TR,
     '            r.link_kind = "sentence" if joined else ""',
     '            r.link_kind = "sentence"', T_LOBESAY),
    ("say-the-kind-is-never-written-to-disk", "project.py",
     '        "link_kind": str(getattr(r, "link_kind", "") or ""),', "", T_LOBESAY),
    ("say-the-kind-is-never-read-back", "project.py",
     '        link_kind=str(rec.get("link_kind", "") or ""),', "", T_LOBESAY),
    # ---- one person, one name
    ("said-the-chapter-remembers-nothing", TR,
     "        remember_said(ctx, page, data.get(\"glossary_additions\") or {})",
     "        pass", T_SAID),
    ("said-nothing-is-sent-with-the-page", TR,
     '        **({"already_said": said} if said else {}),', "", T_SAID),
    ("said-an-empty-one-is-sent-anyway", TR,
     '        **({"already_said": said} if said else {}),',
     '        "already_said": said,', T_SAID),
    ("said-the-same-speaker-is-listed-again-and-again", TR,
     "        if w.lower() not in seen:", "        if True:", T_SAID),
    ("said-a-second-rendering-overwrites-the-first", TR,
     "        if k and v and k not in terms:", "        if k and v:", T_SAID),
    ("said-the-whole-cast-is-sent-for-ever", TR,
     '        out["speakers"] = keep[:40]', '        out["speakers"] = keep',
     T_SAID),
    # ---- the line has to fit, and the dashes come off
    ("fit-a-dash-in-the-middle-stays", TR,
     '    t = re.sub(r"\\s*[—–]+\\s*", ", ", t)', "    t = t", T_FIT),
    ("fit-the-dash-becomes-nothing-instead-of-a-comma", TR,
     '    t = re.sub(r"\\s*[—–]+\\s*", ", ", t)',
     '    t = re.sub(r"\\s*[—–]+\\s*", "", t)', T_FIT),
    ("fit-a-double-comma-is-left-behind", TR,
     '    t = re.sub(r",\\s*,+", ",", t)', "    t = t", T_FIT),
    # The anchor moved when the LEADING dash stopped being covered by this
    # exemption: `if not t or source_has_dash(src)` became two separate tests,
    # and this mutant's old replacement - `if not t:` - is now what the
    # CORRECT source says, which the leftover check rightly read as a mutant
    # left on disk. Same claim, against the shape the exemption has now.
    ("fit-a-source-with-a-dash-loses-its-own", TR,
     "    if source_has_dash(src):\n        return t.strip() or dst",
     "    if False:\n        return t.strip() or dst", T_FIT),
    # ---- a purse you can top up
    ("purse-anybody-can-top-up", "coins.py",
     '    return bool(os.environ.get(TEST_PURSE)) and not remote()',
     "    return True", T_PURSE),
    ("purse-an-account-can-be-topped-up-too", "coins.py",
     '    return bool(os.environ.get(TEST_PURSE)) and not remote()',
     "    return bool(os.environ.get(TEST_PURSE))", T_PURSE),
    ("purse-the-screen-is-not-told", "coins.py",
     '                "buy_url": BUY_URL, "can_top_up": can_top_up(),',
     '                "buy_url": BUY_URL, "can_top_up": False,', T_PURSE),
    ("purse-an-account-is-told-it-can", "coins.py",
     '        got["can_top_up"] = False       # never, on an account',
     '        got["can_top_up"] = True', T_PURSE),
    ("purse-the-button-is-always-drawn", "static/js/coins.js",
     "  if(!w.can_top_up) return '';", "  if(false) return '';", T_PURSE),
    # ---- the line the page can hold, and the shout on it
    ("hold-a-round-balloon-is-measured-as-its-box", TR,
     "    m = getattr(region, \"bubble_mask\", None)\n    if m is not None:",
     "    m = None\n    if m is not None:", T_HOLD),
    ("hold-a-box-with-nothing-in-it-still-promises-room", TR,
     "    return n if n >= 4 else 0", "    return n", T_HOLD),
    ("hold-the-type-size-does-not-come-into-it", TR,
     "    n = int(px * BALLOON_PACK / (CHAR_AREA * size * size))",
     "    n = int(px * BALLOON_PACK / (CHAR_AREA * 144))", T_HOLD),
    ("hold-a-balloon-is-packed-to-its-edges", TR,
     "BALLOON_PACK = 0.55", "BALLOON_PACK = 1.0", T_HOLD),
    ("hold-the-project-minimum-is-ignored", ED,
     '        p.ctx.min_font = int(s.get("min_font") or 12)',
     "        p.ctx.min_font = 12", T_HOLD),
    ("hold-a-snug-line-is-nagged-about", TR,
     "OVER_FITS = 1.25", "OVER_FITS = 1.0", T_HOLD),
    ("hold-nothing-is-ever-too-long", TR,
     "    if room and n > room * OVER_FITS:", "    if False:", T_HOLD),
    ("shout-a-single-mark-counts-as-a-run", TR,
     '_RUN = re.compile(r"[!?！？]{2,}")', '_RUN = re.compile(r"[!?！？]{1,}")',
     T_HOLD),
    ("shout-only-a-run-of-one-mark-counts", TR,
     '_RUN = re.compile(r"[!?！？]{2,}")',
     '_RUN = re.compile(r"([!?！？])\\1{1,}")', T_HOLD),
    ("shout-a-quieter-line-is-not-mentioned", TR,
     "    if was >= 2 and now < was:", "    if False:", T_HOLD),
    ("shout-a-louder-line-is-mentioned-too", TR,
     "    if was >= 2 and now < was:", "    if was >= 2 and now != was:",
     T_HOLD),
    # The budget moved to the FLOOR when lee asked for the accurate line
    # whatever it costs in type size, so the note now means "will not go in at
    # all" rather than "will be small". These two hold that.
    ("hold-the-note-is-taken-at-a-comfortable-size-again", TR,
     '                        or too_long(r.dst_text, r,\n'
     '                                    getattr(ctx, "min_font", 12)))',
     '                        or too_long(r.dst_text, r,\n'
     '                                    getattr(ctx, "max_font", 34)))', T_HOLD),
    ("hold-a-length-budget-is-sent-to-the-model-again", TR,
     '                "text": r.src_text,\n',
     '                "text": r.src_text,\n'
     '                "src_char_count": len(r.src_text),\n', T_HOLD),
    # ---- the size the reader gets, and the two dashes that got there first
    #
    # A hyphen-minus standing alone is a dash the page printed. Page 002's
    # title plate is framed with two of them, and reading it as no-dash cost
    # the plate its frame.
    ("size-a-typed-hyphen-is-not-a-dash", TR,
     "            or bool(_LOOSE_HYPHEN.search(s)))", "            )", T_SIZE),
    ("size-a-hyphen-inside-a-word-counts-too", TR,
     r'_LOOSE_HYPHEN = re.compile(r"(?:^|\s)-+(?=\s|$)")',
     r'_LOOSE_HYPHEN = re.compile(r"-+")', T_SIZE),
    ("size-only-a-hyphen-at-the-very-start-counts", TR,
     r'_LOOSE_HYPHEN = re.compile(r"(?:^|\s)-+(?=\s|$)")',
     r'_LOOSE_HYPHEN = re.compile(r"^-+(?=\s|$)")', T_SIZE),
    ("size-a-hyphen-at-the-end-of-a-plate-is-not-one", TR,
     r'_LOOSE_HYPHEN = re.compile(r"(?:^|\s)-+(?=\s|$)")',
     r'_LOOSE_HYPHEN = re.compile(r"(?:^|\s)-+(?=\s)")', T_SIZE),
    # An ellipsis in front of a dash still leaves the dash at the edge of the
    # line, because `strip_added_ellipsis` runs next and takes the ellipsis
    # away. Page 039 came back opening with a comma.
    ("size-a-dash-behind-an-ellipsis-is-an-interior-dash", TR,
     'rf"^({_OPENERS}(?:{_ELLIPSIS})?{_OPENERS})[-—–]+\s*"',
     'rf"^({_OPENERS})[-—–]+\s*"', T_SIZE),
    ("size-the-openers-are-eaten-with-the-dash", TR,
     "    t = _EDGE_LEAD.sub(r\"\\1\", t, count=1)",
     "    t = _EDGE_LEAD.sub(\"\", t, count=1)", T_SIZE),
    ("size-only-the-front-of-a-line-has-an-edge", TR,
     "    t = _EDGE_TAIL.sub(r\"\\1\", t, count=1)", "", T_SIZE),
    # Two mutants that stood here are gone as EQUIVALENT, not as caught. `^`
    # and `$` outside `re.M` match once, so dropping `count=1` cannot change a
    # thing; and `hi = max(lo, ...)` was held by the `max(lo, ...)` on the way
    # out, so the inner one was dead and has been removed from the code.
    #
    # The budget is taken at a size the typesetter will actually set. It used
    # to be taken at min_font, which on the measured chapter was 11 against a
    # median chosen size of 32 - the note fired zero times in 134 regions.
    ("size-the-reasoned-character-area-is-kept", TR,
     "CHAR_AREA = 1.05", "CHAR_AREA = 0.6", T_SIZE),
    ("size-the-model-is-asked-to-cut-words-again", TR,
     "- LENGTH IS NOT A CONSTRAINT ON YOU.",
     "- Text must be SHORT and you should cut words.", T_SIZE),
    # ---- the cleaner says what it did
    #
    # `inpaint_page` names a route on every box and flags the ones it is not
    # sure about. None of it reached the project: 134 regions of lee's chapter
    # came back with an empty route and not one clean flag, on a chapter with
    # three boxes that still had their Korean on them.
    ("says-the-report-is-thrown-away-with-the-page", ED,
     "    _keep_the_clean_report(p, i, page)\n    p.pages[i].cleaned = True",
     "    p.pages[i].cleaned = True", T_SAYS),
    ("says-cleaning-writes-the-whole-page-back", ED,
     "    _keep_the_clean_report(p, i, page)\n    p.pages[i].cleaned = True",
     "    _commit_keep_proofread(p, i, page)\n    p.pages[i].cleaned = True",
     T_SAYS),
    ("says-a-box-the-page-never-carried-is-blanked", ED,
     "        if got is None:\n            continue",
     '        if got is None:\n            got = ("", None)', T_SAYS),
    ("says-only-the-route-is-kept", ED,
     '        rec["clean_route"], rec["flagged"] = got',
     '        rec["clean_route"] = got[0]', T_SAYS),
    ("says-the-route-is-not-written-to-the-record", "project.py",
     '        "clean_route": str(getattr(r, "clean_route", "") or ""),',
     '        "clean_route": "",', T_SAYS),
    ("says-a-note-is-not-written-to-the-record", "project.py",
     '        "flagged": r.flagged, "manual": bool(getattr(r, "manual", False)),',
     '        "flagged": None, "manual": bool(getattr(r, "manual", False)),',
     T_SAYS),
    # ---- nothing in front of the line
    #
    # A check on the FINISHED line and not on a step, because the comma lee
    # found was made by two steps that were each right on their own.
    ("front-whatever-is-on-the-front-stays", TR,
     "    m = _LEAD_ANY.match(dst)\n    if not m:\n        return dst",
     "    return dst", T_FRONT),
    ("front-the-source-does-not-get-a-say", TR,
     '    if not (dst or "").strip() or leads_with_a_mark(src):',
     '    if not (dst or "").strip():', T_FRONT),
    ("front-a-line-of-nothing-but-marks-is-emptied", TR,
     "    return (m.group(1) + dst[m.end():]).strip() or dst",
     "    return (m.group(1) + dst[m.end():]).strip()", T_FRONT),
    ("front-the-quote-round-the-line-is-taken-with-the-mark", TR,
     "    return (m.group(1) + dst[m.end():]).strip() or dst",
     "    return dst[m.end():].strip() or dst", T_FRONT),
    ("front-a-quote-counts-as-being-in-front-of-the-words", TR,
     'rf"^({_OPENERS})({_LEAD_MARKS}+\s*)"', 'rf"^()({_LEAD_MARKS}+\s*)"',
     T_FRONT),
    ("front-only-the-first-mark-of-a-run-comes-off", TR,
     'rf"^({_OPENERS})({_LEAD_MARKS}+\s*)"', 'rf"^({_OPENERS})({_LEAD_MARKS}\s*)"',
     T_FRONT),
    ("front-a-comma-is-not-a-mark", TR,
     r'_LEAD_MARKS = r"[,.;:!?…‥・·、。，；：！？—–ー~〜～\-]"',
     r'_LEAD_MARKS = r"[.;:!?…‥・·、。，；：！？—–ー~〜～\-]"', T_FRONT),
    ("front-spanish-opens-a-sentence-and-loses-it", TR,
     r'_LEAD_MARKS = r"[,.;:!?…‥・·、。，；：！？—–ー~〜～\-]"',
     r'_LEAD_MARKS = r"[,.;:!?…‥・·、。，；：！？—–ー~〜～¿¡\-]"', T_FRONT),
    ("front-the-translator-never-asks", TR,
     "                r.dst_text = strip_added_lead(\n"
     "                    strip_added_ellipsis(\n"
     "                        strip_added_dashes(fixed, r.src_text), r.src_text),\n"
     "                    r.src_text)",
     "                r.dst_text = strip_added_ellipsis(\n"
     "                    strip_added_dashes(fixed, r.src_text), r.src_text)",
     T_FRONT),
    ("front-the-proofreader-never-asks", TR,
     "            r.dst_text = strip_added_lead(\n"
     "                strip_added_ellipsis(\n"
     "                    strip_added_dashes(\n"
     '                        normalize_text(str(item.get("translation") or "").strip()),\n'
     "                        r.src_text),\n"
     "                    r.src_text),\n"
     "                r.src_text)",
     "            r.dst_text = strip_added_ellipsis(\n"
     "                strip_added_dashes(\n"
     '                    normalize_text(str(item.get("translation") or "").strip()),\n'
     "                    r.src_text),\n"
     "                r.src_text)", T_FRONT),
    ("front-a-pasted-file-is-taken-as-it-comes", ED,
     "    rec[\"dst_text\"] = strip_added_lead(\n"
     "        strip_added_ellipsis(\n"
     "            typeset_mod.normalize_text(str(text or \"\").strip()), src),\n"
     "        src)",
     "    rec[\"dst_text\"] = strip_added_ellipsis(\n"
     "        typeset_mod.normalize_text(str(text or \"\").strip()), src)",
     T_FRONT),
    # ---- a sound effect you just drew
    ("drew-a-box-can-be-drawn-into-a-group-that-is-away", ED,
     "                if not p.pages[i].shown(rec):", "                if False:",
     T_DREW),
    ("drew-drawing-one-box-unhides-every-group", ED,
     "                        p.pages[i].hidden_kinds = [\n"
     "                            k for k in (p.pages[i].hidden_kinds or [])\n"
     "                            if k != g]",
     "                        p.pages[i].hidden_kinds = []", T_DREW),
    ("drew-the-axis-is-never-read-at-draw-time", ED,
     "                        read_sfx_axis(r, _g)", "                        pass",
     T_DREW),
    ("drew-every-box-is-read-as-a-sound-effect", ED,
     '                if _kinds.family_of(getattr(r, "kind", "")) == "sfx":',
     "                if True:", T_DREW),
    # ---- a box you turned
    ("turn-the-corners-turn-the-other-way", "models.py",
     "        out.append([int(round(cx + dx * ca - dy * sa)),\n"
     "                    int(round(cy + dx * sa + dy * ca))])",
     "        out.append([int(round(cx + dx * ca + dy * sa)),\n"
     "                    int(round(cy - dx * sa + dy * ca))])", T_TURN),
    ("turn-the-box-turns-about-its-own-corner", "models.py",
     "    cx, cy = x + w / 2.0, y + h / 2.0\n"
     "    a = math.radians(float(turn or 0.0))",
     "    cx, cy = x, y\n"
     "    a = math.radians(float(turn or 0.0))", T_TURN),
    ("turn-the-angle-is-read-as-radians", "models.py",
     "    a = math.radians(float(turn or 0.0))", "    a = float(turn or 0.0)",
     T_TURN),
    # `turn-a-detector-box-counts-as-turned` stood here. Its replacement
    # -- is_turned without the `manual` test -- is what the CORRECT source
    # says now that every box may be turned, so the leftover check read it
    # as a mutant left on disk. The claim it made lives on the other way
    # up, as `turn-the-drawn-only-rule-comes-back-to-is_turned` below.
    ("turn-a-straight-box-counts-as-turned", PRJ,
     '    return abs(float(rec.get("turn") or 0.0)) > 0.01',
     '    return True', T_TURN),
    ("turn-a-measured-axis-is-read-as-a-turn", PRJ,
     '    return abs(float(rec.get("turn") or 0.0)) > 0.01',
     '    return abs(float(rec.get("angle") or 0.0)) > 0.01',
     T_TURN),
    ("turn-the-turn-is-not-kept-on-the-record", PRJ,
     '        "turn": round(float(getattr(r, "turn", 0.0) or 0.0), 2),', "",
     T_TURN),
    ("turn-the-turn-is-not-read-back-off-the-record", PRJ,
     '        turn=float(rec.get("turn") or 0.0),', "", T_TURN),
    ("turn-a-sound-effects-letters-stay-put", ED,
     '                            rec["angle"] = max(-89.0, min(89.0, float(\n'
     '                                rec.get("angle") or 0.0) + rec["turn"] - was_turn))',
     "                            pass", T_TURN),
    ("turn-the-axis-is-moved-to-the-turn-not-by-it", ED,
     '                            rec["angle"] = max(-89.0, min(89.0, float(\n'
     '                                rec.get("angle") or 0.0) + rec["turn"] - was_turn))',
     '                            rec["angle"] = rec["turn"]', T_TURN),
    ("turn-every-box-moves-its-axis", ED,
     '                        if _kinds.family_of(rec.get("kind") or "") == "sfx":',
     "                        if True:", T_TURN),
    # The refusal this used to delete is gone -- every box may be turned now.
    # Same claim, the other way up: put the refusal BACK and the tests that say
    # a detector box turns have to notice.
    ("turn-only-a-drawn-box-may-be-turned-again", ED,
     "                        was_turn = float(rec.get(\"turn\") or 0.0)",
     '                        if not rec.get("manual"):\n'
     '                            return self._json({"error": "no"})\n'
     '                        was_turn = float(rec.get("turn") or 0.0)', T_TURN),
    ("turn-the-drawn-only-rule-comes-back-to-is_turned", PRJ,
     '    return abs(float(rec.get("turn") or 0.0)) > 0.01',
     '    return bool(rec.get("manual")) and abs(\n'
     '        float(rec.get("turn") or 0.0)) > 0.01', T_TURN),
    ("turn-the-corner-zones-go-back-to-one-stalk", FR2,
     "  ROTZ.forEach(([rt,bt])=>{",
     "  [].forEach(([rt,bt])=>{", T_TURN),
    ("turn-the-zones-stack-up-on-every-reselect", FR2,
     "  box.querySelectorAll('.hd,.rotz').forEach(h=>h.remove());",
     "  box.querySelectorAll('.hd').forEach(h=>h.remove());", T_TURN),
    ("turn-there-are-no-longer-four-corners", FR2,
     "const ROTZ=[[0,0],[1,0],[0,1],[1,1]];",
     "const ROTZ=[[0,0]];", T_TURN),
    ("turn-the-outline-is-left-upright", ED,
     '                        rec["polygon"] = turned_box(rec["bbox"], rec["turn"])',
     "                        pass", T_TURN),
    ("turn-the-turn-is-taken-as-given", ED,
     '                        rec["turn"] = max(-89.0, min(\n'
     '                            89.0, float(body.get("turn") or 0.0)))',
     '                        rec["turn"] = float(body.get("turn") or 0.0)',
     T_TURN),
    ("turn-the-cleaned-plate-is-kept", ED,
     '                reorder(p, i, stale=("layout" not in body))',
     "                reorder(p, i, stale=False)", T_TURN),
    ("turn-a-resize-straightens-the-box", ED,
     "                    if is_turned(new):\n"
     '                        new["polygon"] = turned_box(new["bbox"], new["turn"])',
     "                    pass", T_TURN),
    ("turn-a-resize-drops-the-turn", ED,
     '                             "draw_box", "link", "box_group", "angle",\n'
     '                             "turn")}',
     '                             "draw_box", "link", "box_group", "angle")}',
     T_TURN),
    ("turn-the-fence-shaves-the-turned-corners", IN,
     "        room = _own_area(r, gray.shape, GLYPH_REACH)\n"
     "        if room is None:\n"
     "            room = np.zeros(gray.shape, bool)",
     "        room = None\n"
     "        if room is None:\n"
     "            room = np.zeros(gray.shape, bool)", T_TURN),
    ("turn-the-erase-mask-is-cut-back-to-the-upright-box", IN,
     "        own = _own_area(r, gray.shape, DILATE_PX)",
     "        own = None", T_TURN),
    ("turn-a-detector-box-is-its-own-fence", IN,
     '    if not getattr(region, "manual", False):\n        return False',
     "    pass", T_TURN),
    ("turn-the-cleaner-reads-the-measured-axis", IN,
     '    return abs(float(getattr(region, "turn", 0.0) or 0.0)) > 0.01',
     '    return abs(float(getattr(region, "angle", 0.0) or 0.0)) > 0.01',
     T_TURN),
    ("turn-the-outline-is-not-grown-by-the-doorstep", IN,
     "    return cv2.dilate(m, np.ones((2 * pad + 1,) * 2, np.uint8)) > 0",
     "    return m > 0", T_TURN),
    ("turn-the-block-is-fitted-into-the-leaning-shape", TS,
     '    if (getattr(region, "manual", False) and abs(turn) > 0.01 and mask is None\n'
     '            and _kinds.family_of(getattr(region, "kind", "") or "") != "sfx"):',
     "    if False:", T_TURN),
    ("turn-a-sound-effect-is-re-laid-as-a-block", TS,
     '            and _kinds.family_of(getattr(region, "kind", "") or "") != "sfx"):',
     "            and True):", T_TURN),
    ("turn-the-fitter-reads-the-measured-axis", TS,
     '    turn = float(getattr(region, "turn", 0.0) or 0.0)',
     '    turn = float(getattr(region, "angle", 0.0) or 0.0)', T_TURN),
    ("turn-the-block-is-fitted-straight-and-left-straight", TS,
     "            lay.rotate = turn", "            pass", T_TURN),
    ("turn-a-turned-block-is-clipped-back-to-its-mask", "render.py",
     '        free = free or (getattr(r, "manual", False)\n'
     '                        and abs(float(getattr(r, "turn", 0.0) or 0.0)) > 0.01)',
     "        pass", T_TURN),
    # ---- only the text, and only inside the bubble
    ("only-the-balloon-box-is-left-on-the-old-page", "project.py",
     '        bb = r.get("bubble_bbox")', "        bb = None", T_ONLY),
    ("only-a-balloon-off-this-half-is-clamped-to-a-sliver", "project.py",
     '            out["bubble_bbox"] = ([bx, btop, bw, bbot - btop]\n'
     "                                  if bbot - btop >= 2 else None)",
     '            out["bubble_bbox"] = [bx, btop, bw, bbot - btop]', T_ONLY),
    ("only-an-empty-placement-area-is-shipped-as-is", "project.py",
     "    if not bubble.any():\n"
     "        x, y, w, h = (int(v) for v in rec[\"bbox\"])\n"
     "        bubble[max(0, y):y + h, max(0, x):x + w] = 255", "", T_ONLY),
    ("only-the-fence-is-the-box-alone", IN,
     "        if bm is not None and getattr(bm, \"shape\", None)[:2] == gray.shape[:2]:\n"
     "            room &= cv2.dilate((bm > 0).astype(np.uint8), reach_k) > 0",
     "        pass", T_ONLY),
    ("only-the-fence-is-the-balloon-with-no-doorstep", IN,
     "            room &= cv2.dilate((bm > 0).astype(np.uint8), reach_k) > 0",
     "            room &= (bm > 0)", T_ONLY),
    ("only-the-model-gets-the-old-generous-padding", IN,
     "MODEL_PAD = 2          # ...and on the one the MODEL is given",
     "MODEL_PAD = 6          # ...and on the one the MODEL is given",
     T_ONLY + ["tests/test_pipeline.py::"
               "test_the_widened_mask_does_not_eat_the_screentone_around_it"]),
    ("only-the-local-seed-is-cut-down-too", IN,
     "DILATE_PX = 3          # anti-aliased glyph edges leave grey haze otherwise",
     "DILATE_PX = 1          # anti-aliased glyph edges leave grey haze otherwise",
     T_ONLY),
    # ---- the last step: asking the model to draw it again
    ("draw-the-redraw-never-runs", IN,
     "    drawn = redraw(page, out, neural, again)", "    drawn = []", T_DRAW),
    ("draw-it-runs-with-no-model-to-ask", IN,
     "    if neural is None or page.image is None or page.image.ndim != 3:",
     "    if page.image is None or page.image.ndim != 3:", T_DRAW),
    ("draw-every-box-is-asked-again", IN,
     "    drawn = redraw(page, out, neural, again)",
     "    drawn = redraw(page, out, neural, page.regions)", T_DRAW),
    ("draw-a-few-pixels-are-worth-a-call", IN,
     "REDRAW_LEAST = 200", "REDRAW_LEAST = 1", T_DRAW),
    ("draw-it-is-asked-about-the-second-pass-part-only", IN,
     "        job = {\"win\": box, \"mask\": _dilated(_u8(patch), MODEL_PAD),\n"
     "               \"tight\": _u8(patch)}",
     "        job = {\"win\": box, \"mask\": _dilated(_u8(r.text_mask[box]), MODEL_PAD),\n"
     "               \"tight\": _u8(r.text_mask[box])}", T_DRAW),
    ("draw-it-is-asked-on-the-plate-instead-of-the-page", IN,
     "        keep = out[ctx].copy()\n"
     "        try:\n"
     "            _run_neural(out, job, neural, again=page.image)",
     "        keep = out[ctx].copy()\n"
     "        try:\n"
     "            _run_neural(out, job, neural)", T_DRAW),
    ("draw-a-refused-answer-is-left-on-the-neighbours", IN,
     "            out[ctx] = keep                # it drew the words back, or refused",
     "            out[box] = keep", T_DRAW),
    ("draw-the-words-may-come-back", IN,
     "        if job.get(\"fell_back\") or _away(out[box]) < REDRAW_GHOST * had:\n"
     "            out[ctx] = keep                # it drew the words back, or refused\n"
     "            continue",
     "        pass", T_DRAW),
    ("draw-a-refusal-is-kept", IN,
     "        if job.get(\"fell_back\") or _away(out[box]) < REDRAW_GHOST * had:",
     "        if _away(out[box]) < REDRAW_GHOST * had:", T_DRAW),
    # ---- the fill that is marked, and the patch that is refused
    ("slab-the-fill-is-never-checked", IN,
     "            if _slab_worked(page.image[w], tried, ink):\n"
     "                slab = (wide, level)\n"
     "            else:\n"
     "                mine = False",
     "            slab = (wide, level)", T_SLAB),
    ("slab-a-failed-fill-is-used-anyway", IN,
     "            if _slab_worked(page.image[w], tried, ink):",
     "            if True or _slab_worked(page.image[w], tried, ink):", T_SLAB),
    ("slab-every-fill-is-thrown-away", IN,
     "            if _slab_worked(page.image[w], tried, ink):",
     "            if False and _slab_worked(page.image[w], tried, ink):",
     T_SLAB),
    ("slab-the-check-looks-at-the-page-instead-of-the-fill", IN,
     "            if _slab_worked(page.image[w], tried, ink):",
     "            if _slab_worked(page.image[w], page.image[w], ink):", T_SLAB),
    ("slab-the-line-is-loose-enough-to-let-024-through", IN,
     "SLAB_LEFT = 0.10", "SLAB_LEFT = 0.30", T_SLAB),
    ("slab-the-line-is-tight-enough-to-refuse-every-fill", IN,
     "SLAB_LEFT = 0.10", "SLAB_LEFT = 0.001", T_SLAB),
    ("slab-the-check-reads-the-bare-strokes-and-not-their-edges", IN,
     "    look = _dilated(_u8(ink), DILATE_PX + 1) > 0",
     "    look = _u8(ink) > 0", T_SLAB),
    ("slab-an-unrecorded-box-is-called-a-failure", IN,
     "    if look.sum() < 60:\n"
     "        return True                      # nothing recorded to check against",
     "    if look.sum() < 60:\n"
     "        return False", T_SLAB),
    ("slab-a-blank-box-is-called-a-failure", IN,
     "    if was < 1.0:\n"
     "        return True                      # there was nothing there to remove",
     "    if was < 1.0:\n"
     "        return False", T_SLAB),
    ("grain-a-median-is-painted-over-texture", IN,
     "        if around.sum() > 200 and float(held[around].std()) >= SECOND_GRAIN:\n"
     "            continue",
     "        pass", T_GRAIN),
    ("grain-the-line-lets-hatching-through", IN,
     "SECOND_GRAIN = 22.0", "SECOND_GRAIN = 90.0", T_GRAIN),
    ("grain-the-line-refuses-plain-paper", IN,
     "SECOND_GRAIN = 22.0", "SECOND_GRAIN = 1.0", T_GRAIN),
    ("grain-the-writing-is-measured-as-if-it-were-texture", IN,
     "        writing = ref | (_letterlike(focus_ink(page.image[box])) > 0)",
     "        writing = ref", T_GRAIN),
    ("grain-it-is-measured-through-the-writing-as-well", IN,
     "        around = ~(_dilated(_u8(writing), MODEL_PAD) > 0)",
     "        around = np.ones(ref.shape, bool)", T_GRAIN),
    ("grain-the-model-is-refused-the-same-boxes", IN,
     "        if neural is not None:\n"
     "            job = {\"win\": box, \"mask\": wide, \"tight\": _u8(ink)}",
     "        if False:\n"
     "            job = {\"win\": box, \"mask\": wide, \"tight\": _u8(ink)}",
     T_GRAIN),
    ("bays-the-shape-keeps-its-bites", BALL,
     "    return ((mask > 0) | ((hull > 0) & (keep > 0))).astype(np.uint8) * 255",
     "    return mask", T_BAYS),
    ("bays-the-hull-alone-decides", BALL,
     "    return ((mask > 0) | ((hull > 0) & (keep > 0))).astype(np.uint8) * 255",
     "    return ((mask > 0) | (hull > 0)).astype(np.uint8) * 255", T_BAYS),
    ("bays-the-text-box-alone-decides", BALL,
     "    return ((mask > 0) | ((hull > 0) & (keep > 0))).astype(np.uint8) * 255",
     "    return ((mask > 0) | (keep > 0)).astype(np.uint8) * 255", T_BAYS),
    ("bays-a-region-with-no-box-is-filled-to-its-hull", BALL,
     "    if len(box) != 4:\n        return mask",
     "    if len(box) != 4:\n        box = (0, 0, mask.shape[1], mask.shape[0])",
     T_BAYS),
    # (`bays-a-box-of-no-width-still-counts` stood here and was EQUIVALENT: a
    # box of no width slices to nothing anyway. The guard it mutated has been
    # taken out of the code rather than left as a line no test can see.)
    ("bays-the-finder-stores-the-shape-it-had", BALL,
     "    mask = _no_bays_in_the_writing(r, mask, outer)", "", T_BAYS),
    ("bays-the-stored-bbox-is-taken-from-the-old-shape", BALL,
     "    mask = _no_bays_in_the_writing(r, mask, outer)\n"
     "    cnts, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL,\n"
     "                               cv2.CHAIN_APPROX_SIMPLE)\n"
     "    outer = max(cnts, key=cv2.contourArea)",
     "    mask = _no_bays_in_the_writing(r, mask, outer)", T_BAYS),
    ("bays-a-project-already-on-disk-keeps-them", "project.py",
     "            bubble = _no_bays_in_the_writing(\n"
     "                _Box(), bubble, max(cnts, key=cv2.contourArea))", "", T_BAYS),
    ("bays-the-reload-repairs-a-plain-box-too", "project.py",
     "    if not boxy:\n"
     "        cv2.drawContours(bubble, [poly.reshape(-1, 1, 2)], -1, 255, cv2.FILLED)",
     "    if True:\n"
     "        cv2.drawContours(bubble, [poly.reshape(-1, 1, 2)], -1, 255, cv2.FILLED)",
     T_BAYS),
    # ---- what colour the letters are
    ("ink-the-block-is-taken-for-the-letters", INK,
     "    ink = glyph_ink(img, block, paper)",
     "    ink = block > 0", T_INK),
    ("ink-the-rim-of-a-glyph-is-measured-too", INK,
     "    core = cv2.erode(ink.astype(np.uint8), np.ones((3, 3), np.uint8))",
     "    core = ink.astype(np.uint8)", T_INK),
    ("ink-a-flat-fill-is-called-a-gradient", INK,
     "GRAD_FIT = 0.45", "GRAD_FIT = 0.0", T_INK),
    ("ink-a-real-gradient-is-called-flat", INK,
     "GRAD_FIT = 0.45", "GRAD_FIT = 0.99", T_INK),
    ("ink-shading-counts-as-a-gradient", INK,
     "GRAD_SPAN = 45", "GRAD_SPAN = 5", T_INK),
    ("ink-only-one-of-the-two-gates-has-to-clear", INK,
     "    if r2 >= GRAD_FIT and span >= GRAD_SPAN:",
     "    if r2 >= GRAD_FIT or span >= GRAD_SPAN:", T_INK),
    ("ink-the-gradient-angle-is-measured-the-other-way-round", INK,
     "            float(np.degrees(np.arctan2(gx, gy))) % 360.0, 1)",
     "            float(np.degrees(np.arctan2(gy, gx))) % 360.0, 1)", T_INK),
    ("ink-the-two-stops-come-back-swapped", INK,
     '        style["fg1"], style["fg2"] = _hex(lo), _hex(hi)',
     '        style["fg1"], style["fg2"] = _hex(hi), _hex(lo)', T_INK),
    ("ink-the-angle-goes-out-as-numpys-float", INK,
     "        style[\"grad_angle\"] = round(\n"
     "            float(np.degrees(np.arctan2(gx, gy))) % 360.0, 1)",
     "        style[\"grad_angle\"] = np.round(\n"
     "            np.degrees(np.arctan2(gx, gy)) % 360.0, 1)", T_INK),
    ("ink-a-glow-is-typeset-as-an-outline", INK,
     "            if band and float(np.abs(c - band[0]).max()) > EDGE_FLAT:\n"
     "                break                    # a falloff, not a ring",
     "            if False:\n                pass", T_INK),
    ("ink-anything-a-shade-off-the-paper-is-an-outline", INK,
     "EDGE_STEP = 40", "EDGE_STEP = 5", T_INK),
    ("ink-one-ring-is-enough-to-be-an-outline", INK,
     "        if wide >= 2:", "        if wide >= 1:", T_INK),
    ("ink-the-letters-keep-their-ring-stuck-to-them", INK,
     "                float(far.mean() - near.mean()) >= INK_SPLIT:",
     "                float(far.mean() - near.mean()) >= 9999:", T_INK),
    ("ink-a-gradient-is-split-like-a-ring", INK,
     "            if float((side & inner).sum()) <= NEAR_INSIDE * max(1, side.sum()):",
     "            if True:", T_INK),
    # (No mutant for `>` vs `>=` against Otsu's threshold. OpenCV returns the
    #  value BELOW the cut, so `>=` keeps a ring whose distance lands exactly
    #  on it - and the second split then takes that ring off again and hands
    #  back the same answer. The two cover for each other, which makes it an
    #  equivalent mutant rather than a hole; the strict form is kept because
    #  it is what OpenCV means, not because a test can see it.)
    ("ink-a-colour-somebody-chose-is-overwritten", INK,
     "        fresh = {k: v for k, v in got.items()\n"
     "                 if ov.get(k) in (None, \"\", 0)}",
     "        fresh = dict(got)", T_INK),
    ("ink-a-speck-of-dust-gets-a-colour", INK,
     "MIN_GLYPH = 120", "MIN_GLYPH = 1", T_INK),
    ("ink-the-read-step-never-measures-them", ED,
     "        measure_page(page, p.ink_seen)", "        int(0)", T_INK),
    ("ink-a-bad-measurement-takes-the-read-down", ED,
     "    try:\n        measure_page(page)\n    except Exception:\n"
     "        pass                     # a colour is a nicety; the words are the job",
     "    measure_page(page)", T_INK),
    ("ink-a-glow-is-never-reported", INK,
     "            style.update(_glow(img, ink_rings, beyond))", "            pass", T_INK),
    ("ink-the-blended-rim-counts-as-the-glow", INK,
     "    tail = steps[1:]", "    tail = steps[0:]", T_INK),
    # (No mutant for a rising profile - an outline's shape - being read as a
    #  glow. It cannot happen: a profile that rises is one the outline test has
    #  already claimed, and the glow is only asked when that test found
    #  nothing. The guard that used to be here was unreachable on all six
    #  pages and has been taken out rather than left in untested.)
    ("ink-one-faint-ring-is-a-glow", INK,
     "GLOW_BANDS = 4", "GLOW_BANDS = 2", T_INK),
    ("ink-the-faintest-tail-is-a-glow", INK,
     "GLOW_MIN = 15", "GLOW_MIN = 1", T_INK),
    ("ink-a-shadow-is-never-reported", INK,
     "    style.update(_shadow(img, ink, paper))", "    pass", T_INK),
    ("ink-anything-dark-nearby-is-a-shadow", INK,
     "    if best < SHADOW_HIT:", "    if False:", T_INK),
    # (No mutant for the search running only over positive offsets. Opening it
    #  to negative ones finds nothing: the two lines that blank the wrapped
    #  edge of a rolled mask wipe almost all of it when the shift is negative,
    #  so the candidate never has enough area to be scored. The renderer can
    #  only draw a shadow down and to the right anyway.)
    ("ink-a-symmetric-halo-counts-as-a-shadow", INK,
     "SHADOW_OFF = 1.5", "SHADOW_OFF = 0.0", T_INK),
    ("ink-every-page-keeps-its-own-black", INK,
     "        for k in (\"fg\", \"fg1\", \"fg2\", \"edge\", \"glow\", \"shadow\"):\n"
     "            if k in got:\n                got[k] = _snap(seen, got[k])",
     "        pass", T_INK),
    ("ink-two-colours-that-differ-are-snapped-together", INK,
     "SNAP = 8", "SNAP = 80", T_INK),
    ("ink-the-colour-walks-across-the-chapter", INK,
     "        if _dist(c, value) <= SNAP and (best is None or n > seen[best]):",
     "        if _dist(c, value) <= SNAP:", T_INK),
    ("ink-the-read-step-keeps-no-tally", ED,
     "        measure_page(page, p.ink_seen)", "        measure_page(page)", T_INK),
    # ---- one malformed reply is not the chapter
    ("bad-the-reader-parses-straight-through-again", TR,
     "            except Exception as e:\n                why = str(e)[:120]",
     "            except Exception:\n                raise", T_BADREPLY),
    ("bad-it-asks-once-and-gives-up", TR,
     "OCR_TRIES = 3", "OCR_TRIES = 1", T_BADREPLY),
    ("bad-it-asks-forever", TR, "OCR_TRIES = 3", "OCR_TRIES = 9", T_BADREPLY),
    ("bad-the-retry-repeats-itself-word-for-word", TR,
     "            ask = user if not why else (", "            ask = user if True else (",
     T_BADREPLY),
    ("bad-a-piece-that-never-parses-takes-the-page-with-it", TR,
     "        if data is None:\n            continue",
     "        if data is None:\n            raise ValueError(why)", T_BADREPLY),
    ("bad-a-bare-key-is-left-bare", TR,
     "                if k < n and s[k] == \":\":",
     "                if False:", T_BADREPLY),
    ("bad-any-bareword-at-all-is-made-a-string", TR,
     "                if k < n and s[k] == \":\":",
     "                if True:", T_BADREPLY),
    ("bad-a-single-quote-is-not-a-quote", TR,
     "            if c == \"'\":", "            if False:", T_BADREPLY),
    # ---- ...and it is what the webtoons get by default
    #
    # (The six `fill-` mutants that were here are gone with the setting they
    #  guarded. It was measured over a whole chapter read four ways and never
    #  won: nothing at all under a crop per box, and +50% for the worst of the
    #  four runs on tiles. `crop-a-piece-is-blown-up-again` below is what is
    #  left of them - the one thing worth pinning is that nothing grows.)
    ("crop-a-piece-is-blown-up-again", "ocr.py",
     "    H, W = vis.shape[:2]\n    m = max(H, W)\n    if m > max_side:",
     "    H, W = vis.shape[:2]\n    m = max(H, W)\n    if m != max_side:", T_CROP),
    ("fmt-the-webtoons-do-not-get-the-crops", "ocr.py",
     '    return "boxes" if str(medium or "").lower() in ("manhwa", "manhua") else "auto"',
     '    return "auto"', T_CROP),
    ("fmt-manga-gets-them-too", "ocr.py",
     '    return "boxes" if str(medium or "").lower() in ("manhwa", "manhua") else "auto"',
     '    return "boxes"', T_CROP),
    ("fmt-only-manhwa-and-manhua-is-forgotten", "ocr.py",
     '("manhwa", "manhua")', '("manhwa",)', T_CROP),
    ("fmt-the-read-step-does-not-ask-the-format", ED,
     '    detail = (p.settings.get("ocr_detail")\n'
     '              or detail_for(p.settings.get("medium")))',
     '    detail = p.settings.get("ocr_detail") or "auto"', T_CROP),
    ("fmt-a-choice-made-by-hand-is-overruled", ED,
     '    detail = (p.settings.get("ocr_detail")\n'
     '              or detail_for(p.settings.get("medium")))',
     '    detail = detail_for(p.settings.get("medium"))', T_CROP),
    ("fmt-the-project-pins-a-word-instead", "project.py",
     '            "ocr_detail": "",', '            "ocr_detail": "auto",',
     T_CROP),
    # ---- two lobes of one balloon are one balloon
    ("lobes-the-reach-is-not-the-measured-one", "detect/balloon.py",
     "TOUCH_GAP = 12", "TOUCH_GAP = 400", T_LOBES),
    ("lobes-a-dark-panel-counts-as-paper", "detect/balloon.py",
     "TOUCH_PAPER = 200", "TOUCH_PAPER = 30", T_LOBES),
    ("lobes-anything-joins-not-just-dialogue", "detect/balloon.py",
     '        if r.kind != "bubble" or r.bubble_mask is None:',
     '        if r.bubble_mask is None:', T_LOBES),
    # (There is no "a box with no balloon joins too" mutant. Taking the
    #  `bubble_mask is None` test out changes nothing: `np.asarray(None)` is a
    #  0-d array, its shape is not the page's, and the shape guard on the next
    #  line drops it exactly as the None test would. An equivalent mutant is
    #  not a hole in the tests and chasing it would mean writing a test for a
    #  difference that does not exist.)
    ("lobes-the-paper-is-never-looked-at", "detect/balloon.py",
     "        if not m.any() or _paper_inside(gray, m) < paper:",
     "        if not m.any():", T_LOBES),
    ("lobes-a-hand-set-link-is-overwritten", "detect/balloon.py",
     '        if int(getattr(r, "link", 0) or 0):\n            continue\n',
     "", T_LOBES),
    ("lobes-manga-picks-up-a-number-measured-on-a-webtoon", CTD,
     '        "link_touching": None,', '        "link_touching": 12,', T_LOBES),
    ("lobes-the-webtoons-never-run-it", CTD,
     "                        link_touching=_BL.TOUCH_GAP)",
     "                        link_touching=None)", T_LOBES),
    ("lobes-the-detector-never-calls-it", CTD,
     "    if link_touching:\n"
     "        _BL.link_touching_bubbles(gray, regions, link_touching)\n",
     "", T_LOBES),
    # ---- writing the block head missed is not a sound effect
    ("cover-everything-the-coverage-pass-finds-is-an-effect-again", CTD,
     "    if cover_text:\n        for r in regions:",
     "    if False:\n        for r in regions:", T_COVER),
    ("cover-manga-picks-up-a-number-measured-on-a-webtoon", CTD,
     '        "cover_text": None,', '        "cover_text": 0.25,', T_COVER),
    ("cover-the-ink-bar-is-not-the-measured-one", CTD,
     "                        cover_text=0.25)",
     "                        cover_text=0.15)", T_COVER),
    ("cover-the-character-bar-lets-a-shout-through", CTD,
     "COVER_CHAR = 0.10", "COVER_CHAR = 0.40", T_COVER),
    ("cover-the-size-question-is-never-asked", CTD,
     "                    _glyph_share(gray, r.bbox, r.text_mask) >= COVER_CHAR:",
     "                    False:", T_COVER),
    ("cover-a-tall-shape-is-called-writing", CTD,
     "            if _looks_hand_drawn(gray, r.bbox, r.text_mask, cover_text) or \\\n"
     "                    _taller_than_wide(r.bbox) or \\\n",
     "            if _looks_hand_drawn(gray, r.bbox, r.text_mask, cover_text) or \\\n",
     T_COVER),
    ("cover-a-block-head-box-is-renamed-too", CTD,
     '            if r.kind != "sfx" or id(r) not in from_cover:',
     '            if r.kind != "sfx":', T_COVER),
    ("reach-the-marks-reach-as-far-down-as-they-used-to", CTD,
     "                        join_x=1.8, join_y=0.6,",
     "                        join_x=1.8, join_y=0.9,", T_COVER),
    ("reach-the-sideways-reach-was-cut-with-it", CTD,
     "                        join_x=1.8, join_y=0.6,",
     "                        join_x=1.2, join_y=0.6,", T_TUNE),
    # ---- the paper under the letters is the second opinion
    ("floor-the-floor-is-never-asked", CTD,
     "            elif _paper_under(gray, r.bbox, r.text_mask) >= UNDER_PAPER:\n"
     "                continue\n",
     "", T_SKY),
    ("floor-the-bar-is-not-the-measured-one", CTD,
     "UNDER_PAPER = 210", "UNDER_PAPER = 180", T_SKY),
    ("floor-the-floor-is-read-the-wrong-way-round", CTD,
     "            elif _paper_under(gray, r.bbox, r.text_mask) >= UNDER_PAPER:",
     "            elif _paper_under(gray, r.bbox, r.text_mask) < UNDER_PAPER:",
     T_SKY),
    ("floor-the-letters-are-counted-as-their-own-paper", CTD,
     "    grown = cv2.dilate(ink, np.ones((5, 5), np.uint8)) > 0",
     "    grown = ink > 0", T_SKY),
    # ---- the margin is read close in, and a demoted box stays set type
    ("ring-the-margin-is-read-far-out-again", CTD,
     "RING_LOOK = 0.08", "RING_LOOK = 0.40", T_SKY),
    ("ring-the-floor-is-gone-so-a-small-box-has-no-margin", CTD,
     "RING_FLOOR = 4", "RING_FLOOR = 0", T_SKY),
    ("ring-a-demoted-box-is-judged-as-an-effect-too", CTD,
     '            if r.kind != "freefloat" or id(r) in demoted:',
     '            if r.kind != "freefloat":', T_SKY),
    # ---- Writing on a pale sky is not dialogue
    ("sky-the-margin-bar-is-not-the-measured-one", CTD,
     "LOOSE_RING = 230", "LOOSE_RING = 260", T_SKY),
    ("sky-the-sky-passes-as-paper", CTD,
     "LOOSE_RING = 230", "LOOSE_RING = 200", T_SKY),
    ("sky-manga-picks-up-a-number-measured-on-a-webtoon", CTD,
     '        "loose_bubble": None,', '        "loose_bubble": 230,', T_SKY),
    ("sky-the-demotion-never-runs", CTD,
     "    if loose_bubble:\n        from .balloon import _round_wall_around",
     "    if False:\n        from .balloon import _round_wall_around", T_SKY),
    ("sky-a-box-with-a-balloon-under-it-is-demoted-too", CTD,
     '            if r.kind != "bubble" or r.bubble_mask is not None:',
     '            if r.kind != "bubble":', T_SKY),
    ("sky-the-wall-no-longer-saves-a-balloon", CTD,
     "            if _round_wall_around(gray, r.bbox):\n                continue\n",
     "", T_SKY),
    ("sky-the-margin-is-read-the-wrong-way-round", CTD,
     "            if _ring_paper(gray, r.bbox) >= loose_bubble:",
     "            if _ring_paper(gray, r.bbox) < loose_bubble:", T_SKY),
    ("sky-the-margin-includes-the-writing-it-is-measuring-round", CTD,
     "    frame[max(0, y - ay0):max(0, y - ay0 + h),\n"
     "          max(0, x - ax0):max(0, x - ax0 + w)] = False\n"
     "    v = sub[frame]",
     "    v = sub.reshape(-1)", T_SKY),
    # ---- An outside-text box too empty to be printed type
    ("drawn-the-comparison-is-the-wrong-way-round", CTD,
     "    return fill < thresh",
     "    return fill > thresh", T_DRAWN),
    ("drawn-every-box-is-asked-including-the-dialogue", CTD,
     '            if r.kind == "freefloat" and \\\n',
     '            if r.kind in ("freefloat", "bubble") and \\\n', T_DRAWN),
    ("drawn-the-rule-never-runs", CTD,
     "    if effect_fill:\n        for r in regions:",
     "    if False:\n        for r in regions:", T_DRAWN),
    ("drawn-the-line-is-drawn-through-the-real-writing", CTD,
     "                        effect_fill=0.28)",
     "                        effect_fill=0.35)", T_DRAWN),
    ("drawn-manga-picks-up-a-number-measured-on-a-webtoon", CTD,
     '        "effect_fill": None,\n    },',
     '        "effect_fill": 0.20,\n    },', T_DRAWN),
    ("drawn-one-mark-is-enough-to-judge-a-box-on", CTD,
     "           if int(st[i, cv2.CC_STAT_AREA]) >= DRAWN_PIECE) < 2:",
     "           if int(st[i, cv2.CC_STAT_AREA]) >= DRAWN_PIECE) < 0:", T_DRAWN),
    ("drawn-it-reads-the-artwork-instead-of-the-mask", CTD,
     "    if mask is not None:\n"
     "        ink = (np.asarray(mask)[y0:y1, x0:x1] > 0).astype(np.uint8)\n"
     "    else:\n"
     "        ink = (sub < INK).astype(np.uint8)",
     "    ink = (sub < INK).astype(np.uint8)", T_DRAWN),
    ("drawn-writing-with-no-dark-ink-reads-as-empty", CTD,
     "    if int(ink.sum()) < DRAWN_MIN_INK:\n"
     "        ink = (sub > 200).astype(np.uint8)\n",
     "", T_DRAWN),
    # ---- The box covers the whole of the writing, dialogue included
    ("grow-the-dialogue-is-left-clipped", CTD,
     "                        sfx_grow=0.40, text_grow=0.70,",
     "                        sfx_grow=0.40,", T_TUNE),
    ("grow-the-dialogue-runs-on-the-effects-loose-share", CTD,
     "                        sfx_grow=0.40, text_grow=0.70,",
     "                        sfx_grow=0.40, text_grow=0.40,", T_TUNE),
    ("grow-manga-picks-up-a-number-measured-on-a-webtoon", CTD,
     '        "text_grow": None,\n        # How empty an OUTSIDE TEXT box',
     '        "text_grow": 0.70,\n        # How empty an OUTSIDE TEXT box',
     T_TUNE),
    ("grow-every-box-is-an-effect-again", CTD,
     '        share = sfx_grow if r.kind == "sfx" else text_grow',
     '        share = sfx_grow', T_GROW),
    ("grow-the-effects-are-held-to-the-printed-bar", CTD,
     '        share = sfx_grow if r.kind == "sfx" else text_grow',
     '        share = text_grow', T_GROW),
    ("grow-the-two-shares-are-swapped", CTD,
     '        share = sfx_grow if r.kind == "sfx" else text_grow',
     '        share = text_grow if r.kind == "sfx" else sfx_grow', T_GROW),
    ("grow-the-dialogue-gets-a-second-helping-of-pad", CTD,
     '                                       pad=PAD if r.kind == "sfx" else 0)',
     "                                       pad=PAD)", T_GROW),
    ("tune-manhua-is-an-alias-of-manhwa", CTD,
     'TUNING["manhua"] = dict(TUNING["manhwa"])',
     'TUNING["manhua"] = TUNING["manhwa"]', T_TUNE),
    ("tune-the-webtoons-look-no-harder-than-manga", CTD,
     'TUNING["manhwa"] = dict(TUNING["manga"], mask_thresh=0.20,\n'
     '                        split_gap=3.5, split_height=3.5,\n'
     '                        join_x=1.8, join_y=0.9)',
     'TUNING["manhwa"] = dict(TUNING["manga"])', T_TUNE),
    # The bar was dropped to 0.22 for one turn and lee's own chapter said the
    # head returns nothing at any score. Dropping it again has to fail.
    ("tune-the-webtoons-drop-the-confidence-again", CTD,
     'TUNING["manhwa"] = dict(TUNING["manga"], mask_thresh=0.20,',
     'TUNING["manhwa"] = dict(TUNING["manga"], conf_thresh=0.22,'
     ' mask_thresh=0.20,', T_TUNE),
    ("tune-manhua-is-left-on-mangas-numbers", CTD,
     'TUNING["manhua"] = dict(TUNING["manhwa"])',
     'TUNING["manhua"] = dict(TUNING["manga"])', T_TUNE),
    ("tune-the-gaps-were-narrowed-not-widened", CTD,
     "                        split_gap=3.5, split_height=3.5,",
     "                        split_gap=1.0, split_height=1.0,", T_TUNE),
    ("tune-the-overlap-was-moved-too", CTD,
     'TUNING["manhwa"] = dict(TUNING["manga"], mask_thresh=0.20,',
     'TUNING["manhwa"] = dict(TUNING["manga"], mask_thresh=0.20,\n'
     '                        nms_thresh=0.5,', T_TUNE),
    ("tune-the-webtoons-reach-in-a-circle-like-manga", CTD,
     "                        join_x=1.8, join_y=0.9)",
     "                        join_x=None, join_y=None)", T_TUNE),
    ("tune-the-reach-is-round-and-not-flat", CTD,
     "                        join_x=1.8, join_y=0.9)",
     "                        join_x=1.8, join_y=1.8)", T_TUNE),
    ("tune-the-sideways-reach-is-too-short-for-one-effect", CTD,
     "                        join_x=1.8, join_y=0.9)",
     "                        join_x=0.9, join_y=0.9)", T_TUNE),
    ("tune-the-ellipse-is-never-used", CTD,
     "            if (gx <= near_x * s and gy <= near_y * s) if near_x and near_y \\\n"
     "                    else ((gx * gx + gy * gy) ** 0.5 <= near * s):",
     "            if ((gx * gx + gy * gy) ** 0.5 <= near * s):", T_TUNE),
    ("tune-the-ellipse-takes-either-gap-not-both", CTD,
     "            if (gx <= near_x * s and gy <= near_y * s) if near_x and near_y \\\n"
     "                    else ((gx * gx + gy * gy) ** 0.5 <= near * s):",
     "            if (gx <= near_x * s or gy <= near_y * s) if near_x and near_y \\\n"
     "                    else ((gx * gx + gy * gy) ** 0.5 <= near * s):", T_TUNE),
    ("tune-the-two-reaches-are-swapped", CTD,
     "            if (gx <= near_x * s and gy <= near_y * s) if near_x and near_y \\\n"
     "                    else ((gx * gx + gy * gy) ** 0.5 <= near * s):",
     "            if (gx <= near_y * s and gy <= near_x * s) if near_x and near_y \\\n"
     "                    else ((gx * gx + gy * gy) ** 0.5 <= near * s):", T_TUNE),
    ("tune-the-reach-never-reaches-the-harvest", CTD,
     "    for (x0, y0, x1, y1), sub, ink in _harvest(\n"
     "            tmask, claimed, near_x=join_x, near_y=join_y):",
     "    for (x0, y0, x1, y1), sub, ink in _harvest(tmask, claimed):", T_TUNE),
    ("tune-the-table-is-handed-out-by-reference", CTD,
     '    return dict(TUNING.get(medium or "manga") or TUNING["manga"])',
     '    return TUNING.get(medium or "manga") or TUNING["manga"]', T_TUNE),
    ("tune-an-unknown-format-gets-nothing", CTD,
     '    return dict(TUNING.get(medium or "manga") or TUNING["manga"])',
     '    return dict(TUNING.get(medium or "manga") or {})', T_TUNE),
    ("tune-the-mask-floor-drifts-from-SEG_KEEP", CTD,
     '        "mask_thresh": SEG_KEEP,  # how sure a pixel of the mask must be',
     '        "mask_thresh": 0.25,', T_TUNE),
    ("tune-the-confidence-is-not-the-measured-one", CTD,
     '        "conf_thresh": 0.4,      # how sure the block head must be',
     '        "conf_thresh": 0.5,', T_TUNE),
    ("tune-the-chapter-is-found-on-mangas-numbers-whatever-it-is", PRJ,
     "                **comictext.tuning_for(self.medium))",
     '                **comictext.tuning_for("manga"))', T_TUNE),
    ("tune-the-format-never-reaches-the-detector", PRJ,
     ",\n                **comictext.tuning_for(self.medium))", ")", T_TUNE),
    ("tune-the-second-detector-is-switched-off", CTD,
     "                        craft_x=0.30, craft_y=0.05)",
     "                        craft_x=None, craft_y=None)", T_TUNE),
    ("tune-the-second-detector-reuses-the-masks-reach", CTD,
     "                        craft_x=0.30, craft_y=0.05)",
     "                        craft_x=1.8, craft_y=0.9)", T_TUNE),
    ("tune-the-second-detectors-reach-is-round-and-not-flat", CTD,
     "                        craft_x=0.30, craft_y=0.05)",
     "                        craft_x=0.30, craft_y=0.30)", T_TUNE),
    ("tune-the-second-detector-reaches-too-far-for-one-effect", CTD,
     "                        craft_x=0.30, craft_y=0.05)",
     "                        craft_x=0.50, craft_y=0.10)", T_TUNE),
    ("tune-manga-gets-the-second-detector-too", CTD,
     '        "craft_x": None,\n        "craft_y": None,',
     '        "craft_x": 0.6,\n        "craft_y": 0.3,', T_TUNE),
    # ---- the model finds, the pixels measure
    ("fast-the-morphology-runs-on-the-whole-page-again", CTD,
     "    small = ink[y0:y1, x0:x1]", "    small = ink", T_FAST),
    ("fast-the-crop-has-no-margin-for-the-kernel", CTD,
     "    pad = max(hgap, vgap) + 2", "    pad = 0", T_FAST),
    ("fast-a-big-kernel-is-run-at-full-scale-again", CTD,
     "    f = max(1, int(round(k / float(COARSE))))", "    f = 1", T_FAST),
    ("fast-the-coarse-pass-loses-the-ink-it-is-labelling", CTD,
     "        closed = ((closed > 0) | (ink > 0)).astype(np.uint8)",
     "        closed = (closed > 0).astype(np.uint8)", T_FAST),
    ("fast-the-kernel-does-not-shrink-with-the-page", CTD,
     "        sk = max(3, int(round(k / float(f))))",
     "        sk = max(3, int(round(k)))", T_FAST),
    ("fast-the-parts-are-never-put-back-on-the-page", CTD,
     "        full[y0:y1, x0:x1] = p", "        full[:p.shape[0], :p.shape[1]] = p",
     T_FAST),
    # ---- the next page is not the last one's size
    ("frame-the-element-outranks-the-server-again", JS_VW,
     "  const pw=pageW||d.naturalWidth||1, ph=pageH||d.naturalHeight||1;",
     "  const pw=d.naturalWidth||pageW||1, ph=d.naturalHeight||pageH||1;",
     T_FRAME),
    ("frame-the-drawn-width-comes-from-the-element-again", JS_VW,
     "  const nw=pageW||img.naturalWidth;",
     "  const nw=img.naturalWidth;", T_FRAME),
    ("frame-the-scale-and-the-width-describe-different-pages", JS_VW,
     "  scale=w/nw;", "  scale=w/pageW;", T_FRAME),
    # ---- a black page still looks like a page
    ("edge-a-black-page-has-no-edge", CSS,
     " box-shadow:0 0 0 1px var(--line),0 10px 34px rgba(0,0,0,.55)}\n"
     "/* the reference pane",
     "}\n/* the reference pane", T_EDGE),
    ("edge-the-edge-is-a-glow-not-a-hairline", CSS,
     "#stage img{display:block;max-width:none;border-radius:4px;\n"
     " box-shadow:0 0 0 1px var(--line)",
     "#stage img{display:block;max-width:none;border-radius:4px;\n"
     " box-shadow:0 0 0 6px var(--line)", T_EDGE),
    ("edge-the-edge-moves-the-boxes-off-the-writing", CSS,
     "#stage img{display:block;max-width:none;border-radius:4px;\n"
     " box-shadow:0 0 0 1px var(--line)",
     "#stage img{display:block;max-width:none;border-radius:4px;\n"
     " border:1px solid var(--line);box-shadow:0 0 0 1px var(--line)", T_EDGE),
    ("edge-the-reference-pane-is-left-unframed", CSS,
     "#refImg{display:block;max-width:none;border-radius:4px;opacity:.96;\n"
     " box-shadow:0 0 0 1px var(--line),0 10px 34px rgba(0,0,0,.55)}",
     "#refImg{display:block;max-width:none;border-radius:4px;opacity:.96}",
     T_EDGE),
    # ---- a refused token is said once
    ("token-a-refusal-is-asked-about-again-every-box", ED,
     "    if _refused_for_good(url, token):\n"
     "        _AI_CLEAN_FAIL[\"n\"] += 1",
     "    if False:\n        _AI_CLEAN_FAIL[\"n\"] += 1", T_TOK),
    ("token-a-busy-cleaner-is-latched-too", ED,
     "CLEAN_FATAL = (401, 403)", "CLEAN_FATAL = (401, 403, 429, 500, 503)",
     T_TOK),
    ("token-only-401-latches-and-403-does-not", ED,
     "CLEAN_FATAL = (401, 403)", "CLEAN_FATAL = (401,)", T_TOK),
    ("token-the-latch-ignores-which-token-was-refused", ED,
     "        (url + \"\\x00\" + token).encode(\"utf-8\")).hexdigest()[:16]",
     "        url.encode(\"utf-8\")).hexdigest()[:16]", T_TOK),
    ("token-the-latch-ignores-which-address-was-refused", ED,
     "        (url + \"\\x00\" + token).encode(\"utf-8\")).hexdigest()[:16]",
     "        token.encode(\"utf-8\")).hexdigest()[:16]", T_TOK),
    ("token-clearing-the-warning-leaves-the-latch-on", ED,
     "    _AI_CLEAN_FAIL.update(n=0, msg=\"\", url=\"\", used=0, cached=0,"
     " refused=\"\")",
     "    _AI_CLEAN_FAIL.update(n=0, msg=\"\", url=\"\", used=0, cached=0)",
     T_TOK),
    ("token-a-refusal-still-prints-a-stack", ED,
     "        if not fatal:\n            traceback.print_exc()\n        else:",
     "        if True:\n            traceback.print_exc()\n        if fatal:",
     T_TOK),
    ("token-the-latch-is-never-set", ED,
     "        if fatal:\n"
     "            _AI_CLEAN_FAIL[\"refused\"] = _refusal_key(url, token)",
     "        if False:\n"
     "            _AI_CLEAN_FAIL[\"refused\"] = _refusal_key(url, token)",
     T_TOK),
    ("token-an-undiagnosed-failure-goes-quiet-too", ED,
     "        if not fatal:\n            traceback.print_exc()\n        else:",
     "        if False:\n            traceback.print_exc()\n        else:",
     T_TOK),
    ("token-the-skipped-boxes-are-not-counted", ED,
     "    if _refused_for_good(url, token):\n"
     "        _AI_CLEAN_FAIL[\"n\"] += 1",
     "    if _refused_for_good(url, token):", T_TOK),
    ("token-a-latched-refusal-quietly-downgrades-heal", ED,
     "        if strict:\n"
     "            raise RuntimeError(_AI_CLEAN_FAIL[\"msg\"]\n"
     "                               or \"the cleaner refused the token\")",
     "        if False:\n            raise RuntimeError(\"x\")", T_TOK),
    ("token-the-raised-refusal-says-nothing-useful", ED,
     "            raise RuntimeError(_AI_CLEAN_FAIL[\"msg\"]\n"
     "                               or \"the cleaner refused the token\")",
     "            raise RuntimeError(\"\")", T_TOK),
    # ---- the second detector: what the mask goes black on
    ("craft-the-low-text-floor-drifts", CRF,
     "LOW_TEXT = 0.50", "LOW_TEXT = 0.30", T_EYES),
    ("craft-the-link-threshold-drifts", CRF,
     "LINK_THRESH = 0.80", "LINK_THRESH = 0.40", T_EYES),
    ("craft-the-reach-never-reaches-the-grouping", CRF,
     "    for members in reach_groups(mk, near_x=near_x, "
     "near_y=near_y).values():",
     "    for members in reach_groups(mk).values():", T_EYES),
    ("craft-a-group-forgets-what-it-was-made-of", CRF,
     '                    "pieces": mine})', '                    "pieces": []})',
     T_EYES),
    ("craft-a-panel-sized-group-is-dropped-instead-of-split", CRF,
     "        for b in (item.get(\"pieces\") or []):\n"
     "            if b != box and (b[2] - b[0]) * (b[3] - b[1]) <= limit:\n"
     "                out.append(b)",
     "        continue", T_EYES),
    ("craft-the-fallback-is-a-way-round-the-cap", CRF,
     "            if b != box and (b[2] - b[0]) * (b[3] - b[1]) <= limit:",
     "            if b != box:", T_EYES),
    ("craft-a-group-under-the-cap-is-traded-for-its-pieces-anyway", CRF,
     "        if (box[2] - box[0]) * (box[3] - box[1]) <= limit:\n"
     "            out.append(box)\n            continue",
     "        if False:\n            out.append(box)\n            continue",
     T_EYES),
    ("craft-the-pieces-are-grouped-by-a-second-copy-of-the-rule", CRF,
     "    from .comictext import reach_groups\n",
     "    def reach_groups(m, near_x=None, near_y=None):\n"
     "        return {i: [i] for i in range(len(m))}\n", T_EYES),
    ("craft-a-piece-reaches-by-the-bigger-of-the-two", CRF,
     '             "sz": max(b[2] - b[0], b[3] - b[1])} for b in boxes]',
     '             "sz": 10 ** 6} for b in boxes]', T_EYES),
    ("craft-a-panel-sized-group-still-becomes-a-region", CRF,
     "    for g in _under_cap(groups, limit):",
     "    for g in [i[\"box\"] for i in groups]:", T_EYES),
    ("craft-the-cap-is-taken-against-the-box-not-the-page", CRF,
     "    limit = cap * page_w * page_h",
     "    limit = cap * 720 * 2770", T_EYES),
    ("craft-it-overrules-the-block-head", CRF,
     "            if id(r) in from_block:\n"
     "                hit_block = True\n"
     "                break",
     "            if False:\n"
     "                hit_block = True\n"
     "                break", T_EYES),
    ("craft-a-half-found-effect-is-left-half-found", CRF,
     "        if grow is not None:", "        if False:", T_EYES),
    ("craft-growing-replaces-the-box-instead-of-uniting-it", CRF,
     "            nx0 = max(0, min(x, g[0] - pad))\n"
     "            ny0 = max(0, min(y, g[1] - pad))\n"
     "            nx1 = min(page_w, max(x + w, g[2] + pad))\n"
     "            ny1 = min(page_h, max(y + h, g[3] + pad))",
     "            nx0 = g[0]; ny0 = g[1]; nx1 = g[2]; ny1 = g[3]", T_EYES),
    ("craft-the-bubble-box-is-left-on-the-half-that-was-found", CRF,
     "            if grow.bubble_bbox is not None:\n"
     "                grow.bubble_bbox = grow.bbox",
     "            pass", T_EYES),
    ("craft-a-region-with-no-bubble-box-is-handed-one", CRF,
     "            if grow.bubble_bbox is not None:\n"
     "                grow.bubble_bbox = grow.bbox",
     "            grow.bubble_bbox = grow.bbox", T_EYES),
    ("craft-easyocr-missing-is-a-traceback", CRF,
     "    try:\n        import easyocr  # noqa: F401\n"
     "    except Exception:\n        return False\n    return True",
     "    import easyocr  # noqa: F401\n    return True", T_EYES),
    # ---- 1, 2, 3 and nothing else
    ("keys-four-still-picks-a-sub-type", RO,
     "  return (n >= 1 && n <= 3) ? KIND_FAMILIES[n - 1] : null;",
     "  if(n<=3) return KIND_FAMILIES[n-1];\n"
     "  const r=regions.find(x=>x.id===sel);\n"
     "  const subs=subsOf(familyOf(r?r.kind:'bubble'));\n"
     "  return (subs[n-4]||{}).key || null;", T_FAM),
    ("keys-a-letter-key-retypes-the-box", RO,
     "  else if(view==='original' && !e.altKey && sel!=null\n"
     "          && kindForKey(+e.key)){",
     "  else if(view==='original' && !e.altKey && sel!=null\n"
     "          && (kindForKey(+e.key)||KIND_FAMILIES[0])){", T_FAM),
    # ---- cutting a page by hand
    ("cut-the-boxes-are-left-behind", PRJ,
     "            clipped += self._carry_regions(pg, half, at if k else 0,\n"
     "                                           half.height)\n", "", T_CUT),
    ("cut-the-second-halfs-boxes-keep-the-old-page-s-coordinates", PRJ,
     "            clipped += self._carry_regions(pg, half, at if k else 0,",
     "            clipped += self._carry_regions(pg, half, 0,", T_CUT),
    ("cut-a-box-goes-to-the-half-its-top-is-in", PRJ,
     "        mid = y + h / 2 - dy", "        mid = y - dy", T_CUT),
    ("cut-a-straddling-box-hangs-off-the-end", PRJ,
     '        out["bbox"] = [x, top, w, bot - top]',
     '        out["bbox"] = [x, y - dy, w, h]', T_CUT),
    ("cut-the-typeset-frame-stays-where-it-was", PRJ,
     '                lay["frame"] = [fx, fy - dy, fw, fh]',
     '                lay["frame"] = [fx, fy, fw, fh]', T_CUT),
    ("cut-a-hidden-box-comes-back-visible", PRJ,
     '            if r.get("id") in (src.hidden_ids or []):\n'
     '                dst.hidden_ids.append(r["id"])\n', "", T_CUT),
    ("cut-the-stale-plate-is-carried-over", PRJ,
     "            half.cleaned = half.typeset = half.exported = False",
     "            half.cleaned, half.typeset = pg.cleaned, pg.typeset", T_CUT),
    ("join-the-second-pages-boxes-are-not-pushed-down", PRJ,
     "            self._carry_regions(pg, one, -y, one.height)\n"
     "            one.detected = one.detected or pg.detected",
     "            self._carry_regions(pg, one, 0, one.height)\n"
     "            one.detected = one.detected or pg.detected", T_CUT),
    ("join-a-painted-page-is-joined-anyway", PRJ,
     "        painted = [pg.name for pg in run if self._painted(pg)]",
     "        painted = []", T_CUT),
    ("cut-painting-is-not-what-stops-it", PRJ,
     "        return bool(pg.paint_overlay or pg.paint_over or pg.paint_layers\n"
     "                    or pg.custom_clean)",
     "        return bool(pg.custom_clean)", T_CUT),
    ("cut-a-painted-page-is-cut-anyway", PRJ,
     "        if self._painted(pg):\n"
     "            return False, (\"there are touch-up strokes or a clean plate of \"",
     "        if False:\n"
     "            return False, (\"there are touch-up strokes or a clean plate of \"",
     T_CUT),
    ("cut-a-page-with-boxes-on-it-is-refused-again", PRJ,
     "        if self._painted(pg):\n"
     "            return False, (\"there are touch-up strokes or a clean plate of \"",
     "        if pg.regions or self._painted(pg):\n"
     "            return False, (\"there are touch-up strokes or a clean plate of \"",
     T_CUT),
    ("cut-the-edges-are-fair-game", PRJ,
     "        if not (16 <= at <= h - 16):",
     "        if not (0 <= at <= h):", T_CUT),
    ("cut-the-halves-are-the-wrong-way-round", PRJ,
     "        for k, part in enumerate((img[:at], img[at:])):",
     "        for k, part in enumerate((img[at:], img[:at])):", T_CUT),
    ("cut-the-second-half-starts-a-row-late", PRJ,
     "        for k, part in enumerate((img[:at], img[at:])):",
     "        for k, part in enumerate((img[:at], img[at + 1:])):", T_CUT),
    ("cut-the-new-pages-are-appended-not-inserted", PRJ,
     "        self.pages[i:i + 1] = halves",
     "        self.pages[i:i + 1] = []\n        self.pages += halves", T_CUT),
    ("cut-the-page-you-split-is-deleted", PRJ,
     "            shutil.move(pg.path, os.path.join(keep, os.path.basename(pg.path)))",
     "            os.remove(pg.path)", T_CUT),
    ("cut-a-second-split-writes-over-the-first", PRJ,
     "            while os.path.exists(os.path.join(folder, name)):\n"
     "                name = f\"{stem}{'ab'[k]}{n}{ext}\"\n"
     "                n += 1\n",
     "", T_CUT),
    ("cut-the-halves-report-the-old-size", PRJ,
     "            made.append((name, part.shape[1], part.shape[0]))",
     "            made.append((name, img.shape[1], img.shape[0]))", T_CUT),
    # ---- joining two back into one
    ("join-the-boxes-are-left-behind", PRJ,
     "            self._carry_regions(pg, one, -y, one.height)\n",
     "", T_CUT),
    ("join-runs-off-the-end-of-the-chapter", PRJ,
     "        if not (0 <= i and i + n <= len(self.pages)):",
     "        if not (0 <= i and i < len(self.pages)):", T_CUT),
    ("join-a-narrow-page-is-put-flush-left", PRJ,
     "            off = (w - a.shape[1]) // 2",
     "            off = 0", T_CUT),
    ("join-the-padding-is-black-whatever-the-paper-is", PRJ,
     "            pad = np.full((a.shape[0], w, 3), a[0, 0], np.uint8)",
     "            pad = np.zeros((a.shape[0], w, 3), np.uint8)", T_CUT),
    ("join-only-ever-takes-two", PRJ,
     "        n = max(2, int(count))", "        n = 2", T_CUT),
    ("join-the-pages-you-joined-are-deleted", PRJ,
     "                shutil.move(pg.path, os.path.join(keep,\n"
     "                                                  os.path.basename(pg.path)))",
     "                os.remove(pg.path)", T_CUT),
    ("cut-the-gaps-are-not-offered", PRJ,
     "        return _strip.gutters(flat)", "        return []", T_CUT),
    ("cut-a-refusal-comes-back-as-a-200", PY,
     "                ok, why = p.split_page(i, int(body.get(\"at\") or 0))\n"
     "                if not ok:\n"
     "                    return self._json({\"error\": why}, 400)",
     "                ok, why = p.split_page(i, int(body.get(\"at\") or 0))\n"
     "                if False:\n"
     "                    return self._json({\"error\": why}, 400)", T_CUT),
    ("cut-the-browser-is-not-told-the-page-is-painted", PY,
     '                                   "busy": Project._painted(p.pages[i])})',
     '                                   "busy": False})', T_CUT),
    ("knife-the-preview-asks-for-the-same-url-every-time", JS_CUT,
     "  $('cutImg').src = '/img/' + i + '?v=' + encodeURIComponent(g.key || 'x');",
     "  $('cutImg').src = '/img/' + i;", T_CUT),
    ("knife-the-preview-key-is-not-the-pictures-own", PY,
     '                                   "key": _scan_key(p, i),',
     '                                   "key": str(i),', T_CUT),
    ("knife-the-line-is-drawn-as-a-percentage-again", JS_CUT,
     "  line.style.top = (img.offsetTop + at * img.offsetHeight) + 'px';",
     "  line.style.top = (at * 100) + '%';", T_CUT),
    ("knife-the-line-ignores-where-the-picture-starts", JS_CUT,
     "  line.style.top = (img.offsetTop + at * img.offsetHeight) + 'px';",
     "  line.style.top = (at * img.offsetHeight) + 'px';", T_CUT),
    ("knife-the-preview-scrolls-instead-of-fitting", CSS,
     "#cutImg{display:block;max-width:100%;max-height:52vh;width:auto;height:auto}",
     "#cutImg{display:block;width:100%;height:auto}", T_CUT),
    ("knife-the-line-snaps-away-from-the-pointer-again", JS_CUT,
     "  row = Math.round(row);\n  const line = $('cutLine');",
     "  const near=_cutGaps.filter(g=>Math.abs(g-row)<=60);\n"
     "  if(near.length) row=near[0];\n"
     "  row = Math.round(row);\n  const line = $('cutLine');", T_CUT),
    ("knife-the-edges-are-pulled-back-from-again", JS_CUT,
     "  row = Math.round(row);\n  const line = $('cutLine');",
     "  row = Math.max(16, Math.min(_cutH - 16, Math.round(row)));\n"
     "  const line = $('cutLine');", T_CUT),
    ("knife-a-cut-in-the-top-sixteen-rows-is-offered", JS_CUT,
     "  const tight = (row < EDGE || row > _cutH - EDGE);",
     "  const tight = false;", T_CUT),
    ("knife-the-drag-comes-back", JS_CUT,
     "  wrap.addEventListener('click', cutFromEvent);",
     "  wrap.addEventListener('pointermove', cutFromEvent);", T_CUT),
    ("knife-the-gap-readout-is-always-on", JS_CUT,
     "  const on = _cutGaps.some(g => Math.abs(g - row) <= 2);",
     "  const on = true;", T_CUT),
    ("knife-joining-backwards-joins-forwards", JS_CUT,
     "  doCut('/api/page/' + (cur - 1) + '/merge', {count: 2},",
     "  doCut('/api/page/' + cur + '/merge', {count: 2},", T_CUT),
    ("knife-the-first-page-is-offered-a-page-before-it", JS_CUT,
     "  $('cutPrev').disabled = i < 1;", "  $('cutPrev').disabled = false;",
     T_CUT),
    ("knife-the-last-page-is-offered-a-page-after-it", JS_CUT,
     "  $('cutNext').disabled = i + 1 >= proj.pages.length;",
     "  $('cutNext').disabled = false;", T_CUT),
    ("knife-the-button-is-there-on-manga-too", JS_VW,
     "  const strip = (typeof stripMedium === 'function') ? stripMedium() : true;",
     "  const strip = true;", T_CUT),
    ("knife-the-button-never-follows-the-format-menu", JS_IO,
     "  if(typeof syncViewChrome==='function') syncViewChrome();\n"
     "  stripPixels();", "  stripPixels();", T_CUT),
    # ---- and where the strip settings live
    ("web-the-settings-are-shown-on-manga-too", JS_IO,
     "  if(box) box.style.display = stripMedium() ? 'block' : 'none';",
     "  if(box) box.style.display = 'block';", T_WEB),
    ("web-the-settings-are-never-shown", JS_IO,
     "  if(box) box.style.display = stripMedium() ? 'block' : 'none';",
     "  if(box) box.style.display = 'none';", T_WEB),
    ("web-changing-the-format-does-not-move-them", JS_IO,
     "  else if(typeof saveSettings==='function') saveSettings();\n"
     "  stripSettings();\n}",
     "  else if(typeof saveSettings==='function') saveSettings();\n}", T_WEB),
    ("web-the-pixels-are-not-scaled-by-the-width", JS_IO,
     "      + `${Math.round(w*tall).toLocaleString()}px a page, and anything past `",
     "      + `${Math.round(tall).toLocaleString()}px a page, and anything past `",
     T_WEB),
    ("web-the-two-switches-can-disagree", JS_IO,
     "  const a=$('restitch_strips'), b=$('restitch_new');\n"
     "  if(a) a.checked=on;\n  if(b) b.checked=on;",
     "  const a=$('restitch_strips'), b=$('restitch_new');\n"
     "  if(a) a.checked=on;", T_WEB),
    ("web-the-file-tab-switch-starts-off", HTM,
     '<input type="checkbox" id="restitch_new" checked',
     '<input type="checkbox" id="restitch_new"', T_WEB),
    ("web-the-multiple-is-saved-as-a-pixel-count", JS_PJ,
     "    strip_tall:(+($('strip_tall')||{}).value||3.5),",
     "    strip_tall:2400,", T_WEB),
    ("web-the-bar-never-goes-away", JS_IO,
     "  if(at===false){ box.style.display='none'; return; }",
     "  if(at===false){ return; }", T_WEB),
    ("web-the-bar-invents-a-number-for-the-re-cut", JS_IO,
     "  if(at===null){ outer.classList.add('wait'); fill.style.width=''; return; }",
     "  if(at===null){ fill.style.width='90%'; return; }", T_WEB),
    ("strip-closing-a-project-does-not-ask", IO,
     "  const yes=await ask(`Close ${name}?`,", "  const yes=true; ({}(",
     T_STRIP),
    ("strip-closing-a-project-clears-the-story", IO,
     "  await api('/api/reset','POST',{keep_settings:true});\n"
     "  _seenPages=new Set(); selPages=new Set();\n"
     "  sel=null; cur=0; lastExportDir=''; setRegions([]);\n"
     "  $('results').innerHTML='';\n"
     "  await loadProject();\n"
     "  if(typeof refreshExports==='function') await refreshExports();\n"
     "  staged=[]; renderStaged();\n"
     "  $('pkmsg').textContent='';\n"
     "  setTab('new');",
     "  await api('/api/reset','POST',{keep_settings:false});\n"
     "  _seenPages=new Set(); selPages=new Set();\n"
     "  sel=null; cur=0; lastExportDir=''; setRegions([]);\n"
     "  $('results').innerHTML='';\n"
     "  await loadProject();\n"
     "  if(typeof refreshExports==='function') await refreshExports();\n"
     "  staged=[]; renderStaged();\n"
     "  $('pkmsg').textContent='';\n"
     "  setTab('new');", T_STRIP),
    ("strip-the-story-context-is-downloaded-again", HTML,
     '            onclick="exportSettings()">Export story context</button>',
     '            onclick="exportSettings()">Download story context</button>',
     T_STRIP),

    # ---- a block that springs back
    ("spring-a-local-refit-never-reaches-the-panel", FR,
     "  if(best){\n    L.font_size=best[0]; L.lines=best[1]; L.dirty=true;\n"
     "    panelSaysWhatTheLayoutSays(r);\n  }",
     "  if(best){ L.font_size=best[0]; L.lines=best[1]; L.dirty=true; }",
     T_SPRING),
    ("spring-a-local-rewrap-never-reaches-the-panel", FR,
     "  if(lines.length){ L.lines=lines; L.dirty=true; panelSaysWhatTheLayoutSays(r); }",
     "  if(lines.length){ L.lines=lines; L.dirty=true; }", T_SPRING),
    ("spring-the-sync-writes-over-what-is-being-typed", FR,
     "  if(sz && document.activeElement!==sz && L.font_size) sz.value=L.font_size;",
     "  if(sz && L.font_size) sz.value=L.font_size;", T_SPRING),
    ("spring-the-panel-answers-for-any-block", TSE,
     "  const el=(id)=>mine ? $(id) : null;", "  const el=(id)=>$(id);",
     T_SPRING),
    ("spring-the-panel-answers-for-no-block", TSE,
     "  const el=(id)=>mine ? $(id) : null;", "  const el=(id)=>null;",
     T_SPRING),

    # ---- two things said in one balloon
    ("ball-side-by-side-is-decided-by-the-top-edge", BALL,
     "        if side_by_side(a, b):\n"
     "            return a.bbox[0] > b.bbox[0] if rtl else a.bbox[0] < b.bbox[0]\n"
     "        return a.bbox[1] < b.bbox[1]",
     "        return a.bbox[1] < b.bbox[1]", T_BALL),
    ("ball-the-page-direction-is-ignored", BALL,
     "            return a.bbox[0] > b.bbox[0] if rtl else a.bbox[0] < b.bbox[0]",
     "            return a.bbox[0] > b.bbox[0]", T_BALL),
    ("ball-two-columns-count-as-stacked", BALL,
     "        return over > 0.5 * min(ah, bh)",
     "        return over > 4.0 * min(ah, bh)", T_BALL),
    ("ball-two-stacked-count-as-side-by-side", BALL,
     "        return over > 0.5 * min(ah, bh)", "        return True", T_BALL),
    ("ball-the-sections-stay-linked-as-one-sentence", BALL,
     "            r.link = 0\n", "\n", T_BALL),
    ("ball-the-detector-guesses-at-the-link-again", CTD,
     "        regions.extend(block_regions)",
     "        _lk = [r for r in block_regions if r.kind in ('bubble', 'narration')]\n"
     "        if len(_lk) >= 2:\n"
     "            for r in _lk:\n"
     "                r.link = 1\n"
     "        regions.extend(block_regions)", T_BALL),
    ("ball-a-missing-full-stop-is-taken-as-a-carried-sentence", TR,
     "    return a[-1] in _RUNS_ON_END or b[0] in _RUNS_ON_START",
     "    return a[-1] not in _ENDS_IT", T_BALL),
    ("ball-a-full-stop-does-not-settle-it", TR,
     "    if a[-1] in _ENDS_IT:\n        return False\n", "", T_BALL),
    ("ball-a-closing-bracket-hides-the-mark", TR,
     '    a = a.rstrip("」』）)】〕》”\\"\'")',
     "    a = a", T_BALL),
    ("ball-only-the-first-block-is-looked-at", TR,
     "    return a[-1] in _RUNS_ON_END or b[0] in _RUNS_ON_START",
     "    return a[-1] in _RUNS_ON_END", T_BALL),
    ("ball-the-sections-are-read-in-id-order", TR,
     "        members.sort(key=lambda r: (r.order if r.order >= 0 else 0, r.id))",
     "        members.sort(key=lambda r: r.id)", T_BALL),
    ("ball-a-link-set-by-hand-is-overwritten", TR,
     "        g = int(getattr(r, \"box_group\", 0) or 0)\n        if g:",
     "        g = int(getattr(r, \"box_group\", 0) or 0) or 1\n        if g:",
     T_BALL),
    ("ball-reading-a-page-never-asks", PY,
     "    link_sections(regs)\n", "", T_BALL),
    ("ball-the-shares-are-handed-out-in-reading-order", BALL,
     "            r.bubble_mask = shares[i]", "            r.bubble_mask = shares[seq]",
     T_BALL),

    # ---- the card at the end of a chapter
    #
    # Every one of these is something running off an edge, because that is the
    # only way this card has ever been wrong and it is invisible until it is
    # sitting under somebody's last panel.
    ("card-the-address-hangs-off-the-bottom", CARD,
     "    y = max(floor, (h - tall) // 2)",
     "    y = max(floor, (h - tall) // 2) + int(h * 0.10)", T_CARD),
    ("card-the-banner-address-runs-off-the-right", CARD,
     "        f_url = fit(ANTON, URL, w - pad - ux, int(h * 0.190))",
     "        f_url = fit(ANTON, URL, w * 0.40, int(h * 0.190))", T_CARD),
    ("card-the-column-is-not-squeezed-to-fit", CARD,
     "    if tall > room:",
     "    if False:", T_CARD),
    ("card-the-mark-is-a-copy-and-not-the-real-one", CARD,
     '    d = re.search(r\'\\sd="([^"]+)"\', open(MARK_SVG, encoding="utf-8").read())',
     '    d = re.search(r\'(M7 10.*?Z)\', \'M7 10 L18 10 L32 30 L46 10 L57 10 '
     "L57 46 L46.5 46 L46.5 26.5 L35.5 42 L28.5 42 L17.5 26.5 L17.5 47 "
     "L11.5 60 L7 47 Z')", T_CARD),
    ("card-the-dark-one-comes-out-light", CARD,
     "DARK = dict(bg=(11, 13, 18),", "DARK = dict(bg=(245, 245, 245),", T_CARD),
    ("card-there-is-no-address-on-it", CARD,
     'URL = "mangatct.com"', 'URL = ""', T_CARD),

    # ---- a request that went quiet
    ("slow-a-timeout-is-not-retried-at-all", TR,
     "SLOW_TRIES = 3", "SLOW_TRIES = 1", T_SLOW),
    ("slow-a-timeout-is-retried-as-often-as-a-rate-limit", TR,
     "SLOW_TRIES = 3", "SLOW_TRIES = 6", T_SLOW),
    # Two of them, because the retry is written twice - once in `complete` and
    # once in `complete_vision`. That is exactly how one gets fixed and the
    # other does not, so both are held.
    ("slow-the-translator-does-not-retry", TR,
     "                    if slow < SLOW_TRIES:\n"
     "                        time.sleep(min(delay, 20))\n"
     "                        delay *= 2\n"
     "                        continue\n"
     "                    raise RuntimeError(_too_slow(\n"
     '                        "translation", self.model, self.timeout, slow)) from e',
     "                    if False:\n"
     "                        time.sleep(min(delay, 20))\n"
     "                        delay *= 2\n"
     "                        continue\n"
     "                    raise RuntimeError(_too_slow(\n"
     '                        "translation", self.model, self.timeout, slow)) from e',
     T_SLOW),
    ("slow-the-reader-does-not-retry", TR,
     "                    if slow < SLOW_TRIES:\n"
     "                        time.sleep(min(delay, 20))\n"
     "                        delay *= 2\n"
     "                        continue\n"
     "                    raise RuntimeError(_too_slow(\n"
     '                        "reading", self.model, self.timeout, slow)) from e',
     "                    if False:\n"
     "                        time.sleep(min(delay, 20))\n"
     "                        delay *= 2\n"
     "                        continue\n"
     "                    raise RuntimeError(_too_slow(\n"
     '                        "reading", self.model, self.timeout, slow)) from e',
     T_SLOW),
    ("slow-a-dropped-connection-is-not-a-timeout", TR,
     "_WENT_QUIET = (TimeoutError, ConnectionError, http.client.HTTPException)",
     "_WENT_QUIET = (TimeoutError,)", T_SLOW),
    ("slow-a-timeout-wrapped-in-a-urlerror-is-missed", TR,
     '    reason = getattr(e, "reason", None)\n'
     "    return reason is not None and isinstance(reason, _WENT_QUIET)",
     "    return False  # the wrapped kind is missed", T_SLOW),
    ("slow-the-message-does-not-say-which-model", TR,
     'return (f"{model} did not answer within {seconds} seconds, {tries} times "',
     'return (f"a model did not answer within {seconds} seconds, {tries} times "',
     T_SLOW),
    ("slow-a-dead-address-is-retried-like-a-timeout", TR,
     "                if isinstance(e, urllib.error.URLError):\n"
     "                    raise RuntimeError(\n"
     '                        f"could not reach the translation server at "',
     "                if False:\n"
     "                    raise RuntimeError(\n"
     '                        f"could not reach the translation server at "',
     T_SLOW),
    ("slow-an-unknown-error-is-swallowed", TR,
     '                        f"{self.base_url} ({e}). Is it running?") from e\n'
     "                raise\n",
     '                        f"{self.base_url} ({e}). Is it running?") from e\n'
     "                continue\n",
     T_SLOW),

    # ---- what a customer sees
    #
    # The first of these is the bug that started the rewrite: lee refunded a
    # live $4.99 purchase and the page told him he had been GIVEN 500 coins.
    ("look-a-clawback-is-shown-as-money-coming-in", ACCHTML,
     "const IN = new Set(['credit', 'refund']);",
     "const IN = new Set(['credit', 'refund', 'clawback']);", T_LOOK),
    ("look-a-clawback-is-shown-with-no-sign-at-all", ACCHTML,
     "const plus = IN.has(r.kind);",
     "const plus = r.kind !== 'spend';", T_LOOK),
    ("look-the-ledger-says-pack-pack1", ACCHTML,
     "    (m, id) => (PACKS[id] ? 'the ' + PACKS[id] + ' pack' : m));",
     "    (m, id) => m);", T_LOOK),
    ("look-the-refunded-tag-is-read-out-twice", ACCHTML,
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
    # `seed.js` is not run by any test - it needs a Firestore. What IS tested
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
    # one find-and-replace and moving a block of markup is not - every version
    # of it was an attribute change that moved nothing, and a mutant that
    # cannot express the fault proves only that the suite survives a no-op.

    # ---- Focus clean is gone.
    ("focusgone-the-switch-is-read-again", INP,
     "def focus_ink(bgr: np.ndarray, reach: int = FOCUS_REACH,",
     "def in_focus(region) -> bool:\n"
     "    return bool(getattr(region, \"focus\", False))\n"
     "\n"
     "\n"
     "def focus_ink(bgr: np.ndarray, reach: int = FOCUS_REACH,", T_FOCUSGONE),
    ("focusgone-the-stamp-was-not-bumped", INP,
     'ALGO = "2026-08-15-a"', 'ALGO = "2026-08-13-e"', T_FOCUSGONE),
    ("focusgone-the-flag-is-written-back-out", PRJ_PY,
     '        "kind": str(r.kind), "order": int(r.order),',
     '        "focus": bool(getattr(r, "focus", False)),\n'
     '        "kind": str(r.kind), "order": int(r.order),', T_FOCUSGONE),
    ("focusgone-the-plate-watches-it-again", "editor.py",
     '    geo = tuple((r.get("id"), tuple(r.get("bbox") or ()), r.get("kind"))\n'
     '                for r in p.pages[i].regions)',
     '    geo = tuple((r.get("id"), tuple(r.get("bbox") or ()), r.get("kind"),\n'
     '                 bool(r.get("focus", False)))\n'
     '                for r in p.pages[i].regions)', T_FOCUSGONE),

    # ---- The rail, and the story context you can type.
    ("rail-the-title-never-comes-back-out", PRJ_PY,
     '            "context": {"title": getattr(self.ctx, "title", "") or "",',
     '            "context": {',
     T_RAIL),
    ("rail-the-ticks-forget-which-chapter-they-are-for", JS_PJ,
     "    JSON.stringify({byName:true, chapter:_selChapter,",
     "    JSON.stringify({byName:true, chapter:null,", T_RAIL),
    ("rail-another-chapters-ticks-are-adopted", JS_PJ,
     "  if(_selStored && _selStored.chapter===key){",
     "  if(_selStored){", T_RAIL),
    ("rail-the-ticks-are-thrown-away-on-every-reload", JS_PJ,
     "  if(key===null || key===_selChapter) return;",
     "  if(key===null) return;", T_RAIL),
    ("rail-the-default-width-is-back-where-it-was", CSS,
     "#pages{width:210px;", "#pages{width:168px;", T_RAIL),
    ("rail-the-default-in-the-script-drifts-from-the-sheet", JS_PJ,
     "const RAIL_MIN = 120, RAIL_MAX = 460, RAIL_DEFAULT = 210;",
     "const RAIL_MIN = 120, RAIL_MAX = 460, RAIL_DEFAULT = 168;", T_RAIL),
    ("rail-it-can-be-dragged-to-nothing", JS_PJ,
     "  const w=Math.max(RAIL_MIN, Math.min(RAIL_MAX, Math.round(px)));",
     "  const w=Math.round(px);", T_RAIL),
    ("rail-the-width-is-not-remembered", JS_PJ,
     "    try{ localStorage.setItem('mangatl_rail', String(w)); }catch(e){}",
     "    try{ }catch(e){}", T_RAIL),
    ("rail-the-handle-has-no-resize-cursor", CSS,
     "#pagesGrip{flex:0 0 4px;cursor:col-resize;",
     "#pagesGrip{flex:0 0 4px;cursor:default;", T_RAIL),
    ("story-the-boxes-are-never-filled-from-the-project", JS_IO,
     "  if(n===2) pkFillContext();", "  if(n===2) ;", T_RAIL),
    ("story-what-was-typed-is-not-saved", JS_IO,
     "  await pkSaveContext();\n", "", T_RAIL),
    ("story-an-untouched-step-writes-its-empty-boxes-back", JS_IO,
     "  if(!t || !s || !proj || !proj.context || !pkFillContext.primed) return;",
     "  if(!t || !s || !proj || !proj.context) return;", T_RAIL),
    ("story-typing-does-not-open-done", JS_IO,
     "  if(t.value.trim() || s.value.trim()){ d.disabled=false; d.title=''; }",
     "  if(false){ d.disabled=false; d.title=''; }", T_RAIL),

    # ---- One piece of writing, one box; and paper is not a balloon.
    # ---- A box only CRAFT saw needs more than a graze.
    ("alone-a-graze-is-enough-again", CTD,
     "JOIN_ALONE = 0.20",
     "JOIN_ALONE = 0.05", T_ALONE),
    ("alone-the-bar-is-raised-so-high-nothing-mixed-ever-joins", CTD,
     "JOIN_ALONE = 0.20",
     "JOIN_ALONE = 0.99", T_ALONE),
    ("alone-the-provenance-is-never-checked", CTD,
     "            bar = share\n"
     "            if (a.text_mask is None) != (b.text_mask is None):\n"
     "                bar = max(share, JOIN_ALONE)\n",
     "            bar = share\n", T_ALONE),
    ("alone-the-bar-rises-when-BOTH-are-crafts-alone", CTD,
     "            if (a.text_mask is None) != (b.text_mask is None):",
     "            if (a.text_mask is None) or (b.text_mask is None):",
     T_ALONE),
    ("alone-the-bar-rises-when-neither-is-crafts-alone", CTD,
     "            if (a.text_mask is None) != (b.text_mask is None):",
     "            if (a.text_mask is None) == (b.text_mask is None):",
     T_ALONE),
    ("alone-the-raised-bar-can-lower-the-floor", CTD,
     "                bar = max(share, JOIN_ALONE)",
     "                bar = min(share, JOIN_ALONE)", T_ALONE),
    ("alone-the-raised-bar-is-computed-and-then-dropped", CTD,
     "                    and ox * oy >= bar * min(aw * ah, bw * bh)) \\",
     "                    and ox * oy >= share * min(aw * ah, bw * bh)) \\",
     T_ALONE),
    ("onebox-two-boxes-over-one-shout-stay-two", CTD,
     "    regions = _join_overlapping(regions, join_over)",
     "    regions = _join_overlapping(regions, None)", T_ONEBOX),
    ("onebox-the-join-runs-on-every-format", CTD,
     '        "join_over": None,\n',
     '        "join_over": 0.05,\n', T_ONEBOX),
    ("onebox-boxes-that-only-graze-are-joined-too", CTD,
     "JOIN_OVER = 0.05",
     "JOIN_OVER = 0.005", T_ONEBOX),
    # The anchor here had gone stale - the line was rewritten as a `not (...)`
    # some time ago and the mutant had been skipping silently ever since.
    ("onebox-the-overlap-is-measured-against-the-bigger-box", CTD,
     "                    and ox * oy >= bar * min(aw * ah, bw * bh)) \\",
     "                    and ox * oy >= bar * max(aw * ah, bw * bh)) \\",
     T_ONEBOX),
    ("onebox-two-families-are-joined-into-one-answer", CTD,
     "            if _kinds.family_of(a.kind) != _kinds.family_of(b.kind):\n"
     "                continue\n",
     "", T_ONEBOX),
    ("onebox-a-balloon-is-joined-to-its-neighbour", CTD,
     "    live = [r for r in regions if r.bubble_mask is None]",
     "    live = list(regions)", T_ONEBOX),
    ("onebox-only-the-pairs-join-not-the-chain", CTD,
     "            ra, rb = find(id(a)), find(id(b))\n"
     "            if ra != rb:\n"
     "                parent[rb] = ra",
     "            parent[find(id(b))] = find(id(b))", T_ONEBOX),
    ("onebox-the-join-drops-the-other-pieces-ink", CTD,
     "            head.text_mask = masks[0].copy()\n"
     "            for m in masks[1:]:\n"
     "                head.text_mask = np.maximum(head.text_mask, m)",
     "            head.text_mask = masks[0].copy()", T_ONEBOX),
    ("onebox-the-smallest-piece-becomes-the-box", CTD,
     "        head = max(members, key=lambda q: q.bbox[2] * q.bbox[3])",
     "        head = min(members, key=lambda q: q.bbox[2] * q.bbox[3])",
     T_ONEBOX),
    # ...the boxes with nothing written in them
    ("onebox-the-empty-boxes-are-never-thrown-out", CTD,
     "    if stray_fill:\n        regions = [r for r in regions\n",
     "    if False:\n        regions = [r for r in regions\n", T_ONEBOX),
    ("onebox-the-sweep-runs-on-every-format", CTD,
     '        "stray_fill": None,\n    },',
     '        "stray_fill": 0.115,\n    },', T_ONEBOX),
    ("onebox-the-line-is-drawn-through-the-real-fragments", CTD,
     "STRAY_FILL = 0.115",
     "STRAY_FILL = 0.20", T_ONEBOX),
    ("onebox-a-line-of-writing-counts-as-a-stray-mark", CTD,
     "STRAY_PIECES = 2",
     "STRAY_PIECES = 9", T_ONEBOX),
    ("onebox-a-speck-of-dirt-counts-as-a-mark", CTD,
     "STRAY_MARK = 25",
     "STRAY_MARK = 1", T_ONEBOX),
    ("onebox-the-comparison-is-the-wrong-way-round", CTD,
     "    return fill < fill_under",
     "    return fill > fill_under", T_ONEBOX),
    ("onebox-the-marks-are-counted-the-wrong-way-round", CTD,
     "    if marks > STRAY_PIECES:\n        return False",
     "    if marks < STRAY_PIECES:\n        return False", T_ONEBOX),
    ("onebox-it-reads-the-artwork-instead-of-the-mask", CTD,
     "    if mask is not None:\n"
     "        ink = (np.asarray(mask)[y0:y1, x0:x1] > 0).astype(np.uint8)\n"
     "    else:\n"
     "        sub = gray[y0:y1, x0:x1]\n",
     "    if False:\n"
     "        ink = None\n"
     "    else:\n"
     "        sub = gray[y0:y1, x0:x1]\n", T_ONEBOX),
    ("onebox-the-join-runs-before-the-sweep", CTD,
     "    if stray_fill:\n"
     "        regions = [r for r in regions\n"
     "                   if not _a_stray_mark(gray, r.bbox, r.text_mask,"
     " stray_fill)]\n"
     "    regions = _join_overlapping(regions, join_over)",
     "    regions = _join_overlapping(regions, join_over)\n"
     "    if stray_fill:\n"
     "        regions = [r for r in regions\n"
     "                   if not _a_stray_mark(gray, r.bbox, r.text_mask,"
     " stray_fill)]", T_ONEBOX),
    # ...two passes with two answers about one piece of ink
    ("onebox-two-answers-about-one-piece-of-ink-stay-two-boxes", CTD,
     "            if _kinds.family_of(r.kind) != _kinds.family_of(k.kind)"
     " and \\",
     "            if False and \\", T_ONEBOX),
    ("onebox-a-small-effect-inside-a-big-balloon-is-eaten", CTD,
     "DUP_UNEVEN = 0.10",
     "DUP_UNEVEN = 0.0", T_ONEBOX),
    ("onebox-containment-is-read-against-the-bigger-box", CTD,
     "                    inter >= DUP_INSIDE * min(w * h, c * d) and \\",
     "                    inter >= DUP_INSIDE * max(w * h, c * d) and \\",
     T_ONEBOX),
    # ...paper is not a balloon
    ("paper-a-bright-margin-is-still-proof-of-a-balloon", CTD,
     "            if _ring_paper(gray, r.bbox) >= loose_bubble:\n"
     "                if _round_wall_around(gray, r.bbox, roundish=False,\n"
     "                                      lo=ENCLOSE_LO, hi=ENCLOSE_HI,\n"
     "                                      seal=ENCLOSE_SEAL):\n"
     "                    continue",
     "            if _ring_paper(gray, r.bbox) >= loose_bubble:\n"
     "                continue", T_PAPERBALL),
    ("paper-the-wall-is-asked-for-roundness-it-cannot-have", BALLN,
     "    if not roundish:\n        return True",
     "    if False:\n        return True", T_PAPERBALL),
    ("paper-every-wall-answers-yes-whatever-shape-it-is", BALLN,
     "def _round_wall_around(gray: np.ndarray, bbox, roundish: bool = True)"
     " -> bool:",
     "def _round_wall_around(gray: np.ndarray, bbox, roundish: bool = False)"
     " -> bool:", T_PAPERBALL),
    # ---- a word space is not the end of a line
    ("nextto-the-gap-is-never-asked", CTD,
     "                    and not _next_to(a.bbox, b.bbox):",
     "                    and True:", T_ONEBOX),
    ("nextto-a-word-space-ends-the-line", CTD,
     "NEAR_SIDE = 0.75",
     "NEAR_SIDE = 0.05", T_ONEBOX),
    ("nextto-the-whole-page-is-one-paragraph", CTD,
     "NEAR_STACK = 0.35",
     "NEAR_STACK = 5.0", T_ONEBOX),
    ("nextto-boxes-that-do-not-line-up-join-anyway", CTD,
     "NEAR_PERP = 0.80",
     "NEAR_PERP = 0.0", T_ONEBOX),
    ("nextto-the-sideways-gap-is-measured-like-the-stacked-one", CTD,
     "        return (rows >= NEAR_PERP * short\n"
     "                and gx <= NEAR_SIDE * short)",
     "        return (rows >= NEAR_PERP * short\n"
     "                and gx <= NEAR_STACK * short)", T_ONEBOX),
    # ---- letters against drawings, both directions
    ("chars-a-box-with-nothing-in-it-is-kept", CTD,
     "            if art_veto and n == 0:\n                continue",
     "            if False:\n                continue", T_CHARS),
    ("chars-the-veto-runs-on-every-format", CTD,
     '        "art_veto": False,\n',
     '        "art_veto": True,\n', T_CHARS),
    ("chars-a-big-shout-is-left-as-outside-text", CTD,
     "            if fx_chars and n <= fx_chars and cover >= FX_COVER \\\n"
     '                    and _kinds.family_of(r.kind) != "sfx":\n'
     '                r.kind = "sfx"',
     "            if False:\n"
     '                r.kind = "sfx"', T_CHARS),
    ("chars-two-small-syllables-become-a-shout", CTD,
     "FX_COVER = 0.30",
     "FX_COVER = 0.0", T_CHARS),
    ("chars-a-whole-line-of-type-becomes-a-shout", CTD,
     "FX_CHARS = 2",
     "FX_CHARS = 9", T_CHARS),
    ("chars-the-swallowed-writing-is-never-given-back", CTD,
     '            elif fx_chars and _kinds.family_of(r.kind) == "sfx" \\\n'
     "                    and n >= SFX_TEXT_CHARS and med_h <= SFX_TEXT_H * im_w:\n"
     '                r.kind = "freefloat"',
     "            elif False:\n"
     '                r.kind = "freefloat"', T_CHARS),
    ("chars-five-big-characters-are-given-back-too", CTD,
     "SFX_TEXT_CHARS = 6",
     "SFX_TEXT_CHARS = 5", T_CHARS),
    ("chars-tall-characters-count-as-small-ones", CTD,
     "SFX_TEXT_H = 0.09",
     "SFX_TEXT_H = 0.5", T_CHARS),
    ("chars-a-box-in-a-balloon-is-asked-anyway", CTD,
     "            if r.bubble_mask is not None:\n"
     "                kept.append(r)\n"
     "                continue",
     "            if False:\n"
     "                kept.append(r)\n"
     "                continue", T_CHARS),
    # ---- outside text shut inside a frame
    ("frame-enclosed-writing-on-paper-stays-outside-text", CTD,
     '                r.kind = "bubble"',
     '                pass', T_CHARS),
    ("frame-the-enclosure-is-asked-at-the-balloon-thresholds", CTD,
     "ENCLOSE_LO = 20",
     "ENCLOSE_LO = 30", T_CHARS),
    ("frame-the-seal-cannot-bridge-an-ornament-gap", CTD,
     "ENCLOSE_SEAL = 25",
     "ENCLOSE_SEAL = 15", T_CHARS),
    ("frame-writing-on-dark-ground-is-promoted-too", CTD,
     "            if (_ring_paper(gray, r.bbox) >= loose_bubble\n"
     "                    or _paper_under(gray, r.bbox, r.text_mask) >= UNDER_PAPER) \\",
     "            if True \\", T_CHARS),
    # ---- each text gets its own box
    ("owntext-two-texts-stay-one-box", CTD,
     "    if split_texts:\n"
     "        regions = _each_text_its_own_box(regions)",
     "    if False:\n"
     "        regions = _each_text_its_own_box(regions)", T_OWNTEXT),
    ("owntext-the-split-runs-on-every-format", CTD,
     '        "split_texts": False,\n',
     '        "split_texts": True,\n', T_OWNTEXT),
    ("owntext-a-paragraph-is-split-too", CTD,
     "DIAG_ROWCOL = 0.30",
     "DIAG_ROWCOL = 3.0", T_OWNTEXT),
    ("owntext-a-line-of-leading-splits-a-text", CTD,
     "STACK_SPLIT = 0.80",
     "STACK_SPLIT = 0.10", T_OWNTEXT),
    ("owntext-the-stacked-band-is-never-asked", CTD,
     "    if len(bands) >= 2:",
     "    if False:", T_OWNTEXT),
    ("owntext-a-droplet-mark-is-half-a-text", CTD,
     "DIAG_BALANCE = 0.15",
     "DIAG_BALANCE = 0.0", T_OWNTEXT),
    ("owntext-a-drawn-effect-is-split-like-dialogue", CTD,
     '        if _kinds.family_of(r.kind) == "sfx" or r.text_mask is None:\n'
     "            out.append(r)\n"
     "            continue",
     "        if r.text_mask is None:\n"
     "            out.append(r)\n"
     "            continue", T_OWNTEXT),
    ("owntext-the-split-stops-after-one-pass", CTD,
     "            piece.confidence = getattr(r, \"confidence\", 0.0)\n"
     "            todo.append(piece)",
     "            piece.confidence = getattr(r, \"confidence\", 0.0)\n"
     "            out.append(piece)", T_OWNTEXT),
    ("owntext-the-halves-share-the-whole-mask", CTD,
     "            m = (np.isin(lab, [p[5] for p in side])\n"
     "                 & (full > 0)).astype(np.uint8) * 255",
     "            m = (full > 0).astype(np.uint8) * 255", T_OWNTEXT),
    # ---- the shout label defers to a wall, a burst is not bare paper,
    #      the box of a writing region is the writing
    ("shelter-a-shout-in-a-thought-circle-is-deleted-again", CTD,
     '                    and not _sheltered(gray, r.bbox, r.text_mask):',
     '                    and True:', T_FIVE),
    ("shelter-the-paper-gate-is-dropped", CTD,
     "    if not (_ring_paper(gray, bbox) >= LOOSE_RING\n"
     "            or _paper_under(gray, bbox, mask) >= UNDER_PAPER):\n"
     "        return False",
     "    if False:\n"
     "        return False", T_FIVE),
    ("rays-a-burst-reads-as-bare-paper-again", CTD,
     "                if _ring_rays(gray, r.bbox) >= RAYS_DENS \\\n"
     "                        and _ink_chroma(img, r.bbox) < INK_CHROMA:\n"
     "                    continue",
     "                if False:\n"
     "                    continue", T_FIVE),
    ("rays-the-bar-is-under-the-credits", CTD,
     "RAYS_DENS = 0.04",
     "RAYS_DENS = 0.01", T_FIVE),
    ("rays-the-bar-is-over-the-bursts", CTD,
     "RAYS_DENS = 0.04",
     "RAYS_DENS = 0.10", T_FIVE),
    ("shave-the-sword-stays-in-the-box", CTD,
     "            m = np.where(near, m, 0).astype(m.dtype)",
     "            continue\n"
     "            m = np.where(near, m, 0).astype(m.dtype)", T_FIVE),
    ("shave-a-legitimate-fringe-shaves-the-box", CTD,
     "SHAVE_BLOB = 1500",
     "SHAVE_BLOB = 100", T_FIVE),
    ("shave-an-effects-strokes-are-shaved-off", CTD,
     "            if r.bubble_mask is not None or r.text_mask is None \\\n"
     '                    or _kinds.family_of(r.kind) == "sfx":\n'
     "                continue\n"
     "            x, y, w, h = [int(v) for v in r.bbox]\n"
     "            m = np.asarray(r.text_mask)",
     "            if r.bubble_mask is not None or r.text_mask is None:\n"
     "                continue\n"
     "            x, y, w, h = [int(v) for v in r.bbox]\n"
     "            m = np.asarray(r.text_mask)", T_FIVE),
    ("rescue-display-type-is-priced-out-again", CTD,
     "SFX_TEXT_H = 0.15",
     "SFX_TEXT_H = 0.09", T_FIVE),
    ("secondjoin-the-title-stays-two-boxes", CTD,
     "        regions = _join_overlapping(regions, join_over)\n"
     "        for n, r in enumerate(regions):\n"
     "            r.id = n",
     "        for n, r in enumerate(regions):\n"
     "            r.id = n", T_FIVE),
    ("holds-a-fragment-vetoes-the-title-again", CRA,
     "                if ox > 0 and oy > 0 and ox * oy >= BLOCK_HOLDS * ga:\n"
     "                    hit_block = True\n"
     "                    break\n"
     "                continue",
     "                hit_block = True\n"
     "                break", T_HOLDS),
    ("holds-a-balloon-loses-its-veto", CRA,
     "BLOCK_HOLDS = 0.5",
     "BLOCK_HOLDS = 0.99", T_HOLDS),
    # ---- the page list follows the page you are on
    ("follow-the-list-stops-following-the-page", PJ,
     "  keepCurrentPageInView();",
     "  ;", T_FOLLOW),
    ("follow-the-list-jumps-on-every-redraw", PJ,
     "      row.scrollIntoView({block:'nearest', inline:'nearest'});",
     "      row.scrollIntoView({block:'center', inline:'nearest'});", T_FOLLOW),
    ("follow-a-rename-is-scrolled-away-from", PJ,
     "  if(!list || list.querySelector('.nmedit')) return;",
     "  if(!list) return;", T_FOLLOW),
    ("follow-a-missing-method-throws-the-frame-away", PJ,
     "    if(typeof row.scrollIntoView==='function')\n"
     "      row.scrollIntoView({block:'nearest', inline:'nearest'});",
     "    row.scrollIntoView({block:'nearest', inline:'nearest'});", T_FOLLOW),
    # ---- the frame round two sections of one balloon is gone
    ("nogbox-the-editor-draws-the-frame-again", FR2,
     "  const sectioned=r=>{ const g=+(r.box_group||0);"
     " return g>0 && bg[g] && bg[g].length>1; };",
     "  Object.keys(bg).forEach(g=>{ const mem=bg[g];\n"
     "    if(mem.length<2) return;\n"
     "    const dd=document.createElement('div');\n"
     "    dd.className='gbox'; st.appendChild(dd); });\n"
     "  const sectioned=r=>{ const g=+(r.box_group||0);"
     " return g>0 && bg[g] && bg[g].length>1; };", T_NOGBOX),
    ("nogbox-the-sheet-draws-the-frame-again", RND,
     "    groups = {g: m for g, m in groups.items() if len(m) > 1}\n"
     "    sectioned = {id(r) for m in groups.values() for r in m}",
     "    groups = {g: m for g, m in groups.items() if len(m) > 1}\n"
     "    sectioned = {id(r) for m in groups.values() for r in m}\n"
     "    for _g, _mem in sorted(groups.items()):\n"
     "        _xs = [balloon_of(r) for r in _mem]\n"
     "        _x0 = min(b[0] for b in _xs); _y0 = min(b[1] for b in _xs)\n"
     "        _x1 = max(b[0] + b[2] for b in _xs)\n"
     "        _y1 = max(b[1] + b[3] for b in _xs)\n"
     "        ink.rect((_x0, _y0, _x1 - _x0, _y1 - _y0),\n"
     "                 _bgr(kind_colour(_mem[0].get('kind', 'bubble'),\n"
     "                                  custom_kinds)), GROUP_FILL)", T_NOGBOX),
    ("nogbox-the-sections-stop-being-marked", RND,
     "    sectioned = {id(r) for m in groups.values() for r in m}",
     "    sectioned = set()", T_NOGBOX),
    # ---- the frame a caption sits in is its balloon; the late grow
    ("caged-the-frame-is-never-taken-as-the-balloon", CTD,
     "            r.bubble_mask = interior\n"
     "            r.bubble_bbox = tuple(int(v) for v in fb)",
     "            continue\n"
     "            r.bubble_mask = interior", T_CAGED),
    ("caged-a-shared-frame-is-handed-to-both-boxes", CTD,
     "            if shared:\n"
     "                continue\n"
     "            r.bubble_mask = interior",
     "            if False:\n"
     "                continue\n"
     "            r.bubble_mask = interior", T_CAGED),
    ("caged-the-balloon-does-not-persist", CTD,
     "            if cs:\n"
     "                big = max(cs, key=cv2.contourArea)\n"
     "                r.polygon = [[int(a), int(b)] for a, b in"
     " big.reshape(-1, 2)]",
     "            if False:\n"
     "                big = None\n"
     "                r.polygon = None", T_CAGED),
    # There is deliberately NO mutant for the late grow being skipped. The
    # main grow covers every fixture simple enough to build -- the late one
    # only decides for a box whose share of a mark GREW by joining, and a
    # fixture arranging that is a page built to the shape of the answer. The
    # real evidence is the chapter run: 042's joined title measures
    # (35,92,571,210) without the late grow and (35,45,637,337) with it, the
    # difference being the outline contour lee circled. The ORDER (grow, then
    # shave, then join) is pinned by test_the_grow_runs_before_the_shave.
    # ...and the two detectors starting together
    ("fast-the-second-detector-waits-for-the-first-again", CTD,
     "            craft_job = _POOL.submit(_craft.pieces, img)",
     "            craft_job = None\n"
     "            _craft_now = _craft.pieces(img)", T_TOGETHER),
    ("fast-a-page-at-a-time-becomes-a-fleet", CTD,
     'ThreadPoolExecutor(max_workers=1, thread_name_prefix="craft")',
     'ThreadPoolExecutor(max_workers=4, thread_name_prefix="craft")', T_TOGETHER),
    ("paper-the-margin-is-read-the-wrong-way-round", CTD,
     "            if _ring_paper(gray, r.bbox) >= loose_bubble:\n"
     "                if _round_wall_around(gray, r.bbox, roundish=False,",
     "            if _ring_paper(gray, r.bbox) < loose_bubble:\n"
     "                if _round_wall_around(gray, r.bbox, roundish=False,",
     T_PAPERBALL),
    # ---- the models lee asked to be added: Gemini 3.7, the GPT-5.6 tiers and
    # the Qwen 3.7 tiers, and the one of them that cannot be shown a page.
    ("range-gemini-3-7-is-not-sold-direct", COIN,
     '    "gemini-3.7-flash": _google(1.50, 7.50),',
     '    "gemini-3.7-flash-NOPE": _google(1.50, 7.50),', T_MENU),
    ("range-gemini-3-7-is-not-sold-through-the-reseller", COIN,
     '    "google/gemini-3.7-flash": _google(1.50, 7.50),',
     '    "google/gemini-3.7-flash-NOPE": _google(1.50, 7.50),', T_MENU),
    ("range-the-launch-discount-is-written-down-instead", COIN,
     '    "gemini-3.7-flash": _google(1.50, 7.50),',
     '    "gemini-3.7-flash": _google(0.75, 3.75),', T_MENU),
    ("range-3-6-is-met-before-3-7-and-keeps-the-band", COIN,
     '    "google/gemini-3.7-flash": _google(1.50, 7.50),\n'
     '    "google/gemini-3.6-flash": _google(1.50, 7.50),',
     '    "google/gemini-3.6-flash": _google(1.50, 7.50),\n'
     '    "google/gemini-3.7-flash": _google(1.50, 7.50),', T_MENU),
    ("range-the-openai-tiers-are-not-on-the-menu", COIN,
     '    "openai/gpt-5.6-sol": Rate(5.00, 30.00),',
     '    "openai/gpt-5.6-sol-NOPE": Rate(5.00, 30.00),', T_MENU),
    ("range-openai-is-not-a-maker-openrouter-carries", COIN,
     '    "openrouter": ("google/", "anthropic/", "deepseek/", "openai/",'
     ' "qwen/"),',
     '    "openrouter": ("google/", "anthropic/", "deepseek/", "qwen/"),',
     T_MENU),
    ("range-qwen-is-not-a-maker-openrouter-carries", COIN,
     '    "openrouter": ("google/", "anthropic/", "deepseek/", "openai/",'
     ' "qwen/"),',
     '    "openrouter": ("google/", "anthropic/", "deepseek/", "openai/"),',
     T_MENU),
    ("range-the-blind-one-is-offered-a-page-to-read", COIN,
     'NO_SIGHT = ("deepseek-", "qwen3.7-max")',
     'NO_SIGHT = ("deepseek-",)', T_MENU),
    ("range-the-whole-maker-is-called-blind", COIN,
     'NO_SIGHT = ("deepseek-", "qwen3.7-max")',
     'NO_SIGHT = ("deepseek-", "qwen")', T_MENU),
    ("range-the-default-is-left-on-a-model-off-the-menu", "editor.py",
     '    "translate": ("gemini", "gemini-3.7-flash"),',
     '    "translate": ("gemini", "gemini-3.6-flash"),', T_STEP),
    ("range-the-two-copies-of-the-default-part", PRJ,
     '"translate_model": "gemini-3.7-flash", "translate_backend": "gemini",',
     '"translate_model": "gemini-3.6-flash", "translate_backend": "gemini",',
     T_STEP),
    # ---- a box with no writing in it, only marks
    ("marks-nothing-is-ever-only-marks", OCR,
     "        if (cat[0] == \"L\" and cat != \"Lm\") or cat[0] == \"N\":\n"
     "            return False\n"
     "    return True",
     "        if (cat[0] == \"L\" and cat != \"Lm\") or cat[0] == \"N\":\n"
     "            return False\n"
     "    return False", T_MARKS),
    ("marks-a-box-nothing-was-read-in-is-deleted-too", OCR,
     "    t = (text or \"\").strip()\n"
     "    if not t:\n"
     "        return False",
     "    t = (text or \"\").strip()\n"
     "    if not t:\n"
     "        return True", T_MARKS),
    ("marks-a-lone-stretched-sound-counts-as-a-word", OCR,
     'if (cat[0] == "L" and cat != "Lm") or cat[0] == "N":',
     'if cat[0] == "L" or cat[0] == "N":', T_MARKS),
    ("marks-a-number-on-a-sign-is-thrown-away", OCR,
     'if (cat[0] == "L" and cat != "Lm") or cat[0] == "N":',
     'if cat[0] == "L" and cat != "Lm":', T_MARKS),
    ("marks-the-flag-goes-back-to-a-hand-written-list", OCR,
     "    if only_symbols(visible):",
     "    if re.fullmatch(r\"[。、,.!?！？…・\\-—ー~〜]+\", visible):", T_MARKS),
    ("marks-somebodys-own-text-box-is-deleted", ED,
     'if getattr(r, "own_text", False) or getattr(r, "locked", False):',
     'if getattr(r, "locked", False):', T_MARKS),
    ("marks-a-locked-box-is-deleted", ED,
     'if getattr(r, "own_text", False) or getattr(r, "locked", False):',
     'if getattr(r, "own_text", False):', T_MARKS),
    ("marks-a-translated-box-is-deleted", ED,
     '        if (getattr(r, "dst_text", "") or "").strip():\n'
     "            continue",
     "        if False:\n"
     "            continue", T_MARKS),
    ("marks-the-switch-defaults-off", ED,
     'if p.settings.get("drop_symbol_only") is not False:',
     'if p.settings.get("drop_symbol_only") is True:', T_MARKS),
    ("marks-the-switch-is-not-read-at-all", ED,
     'if p.settings.get("drop_symbol_only") is not False:',
     "if True:", T_MARKS),
    ("marks-the-sections-are-linked-before-the-drop", ED,
     '    if p.settings.get("drop_symbol_only") is not False:',
     "    link_sections(regs)\n"
     '    if p.settings.get("drop_symbol_only") is not False:', T_MARKS),
    ("marks-the-page-is-never-renumbered", ED,
     "    if len(page.regions) != before:\n"
     "        reorder(p, i)",
     "    if False:\n"
     "        reorder(p, i)", T_MARKS),
    ("marks-every-read-pays-for-a-renumber", ED,
     "    if len(page.regions) != before:\n"
     "        reorder(p, i)",
     "    if True:\n"
     "        reorder(p, i)", T_MARKS),
    ("marks-the-default-is-off-in-a-new-project", PRJ,
     '            "drop_symbol_only": True,',
     '            "drop_symbol_only": False,', T_MARKS),
    ("marks-the-box-on-screen-starts-unticked", HTM,
     '          <input type="checkbox" id="drop_symbol_only" checked',
     '          <input type="checkbox" id="drop_symbol_only"', T_MARKS),
    ("marks-the-switch-is-never-saved", JSP,
     "    ...ON_SWITCHES.reduce((o,k)=>{",
     "    ...STORY_SWITCHES.reduce((o,k)=>{", T_MARKS),
    ("marks-the-switch-is-never-loaded", JSP,
     "  ON_SWITCHES.forEach(k=>{",
     "  STORY_SWITCHES.forEach(k=>{", T_MARKS),
    # ---- one man, one spelling; and a person is not a glossary term
    ("name-every-capital-is-a-name", TR,
     '            if w[0].isupper():\n                if not starts:',
     '            if w[0].isupper():\n                if True:', T_NAME),
    ("name-a-word-used-in-lower-case-is-still-a-name", TR,
     '    return [w for w in order if w.lower() not in lower]',
     '    return list(order)', T_NAME),
    ("name-a-possessive-is-a-second-name", TR,
     '    return re.sub(r"[\'\u2019]s$", "", w)',
     '    return w', T_NAME),
    ("name-two-letter-words-are-names", TR,
     '                    if len(b) > 2 and b not in mid:',
     '                    if b not in mid:', T_NAME),
    ("drift-a-different-initial-is-still-drift", TR,
     '            if was[0].lower() != now[0].lower():\n                continue',
     '            if False:\n                continue', T_NAME),
    ("drift-a-name-drifts-from-itself", TR,
     '        if now in used:\n            continue',
     '        if False:\n            continue', T_NAME),
    ("drift-nothing-is-ever-close-enough", TR,
     'def name_drift(used, fresh, close: float = 0.72) -> list:',
     'def name_drift(used, fresh, close: float = 0.999) -> list:', T_NAME),
    ("drift-everything-is-close-enough", TR,
     'def name_drift(used, fresh, close: float = 0.72) -> list:',
     'def name_drift(used, fresh, close: float = 0.2) -> list:', T_NAME),
    ("name-the-prose-is-never-remembered", TR,
     '    for n in names_in([r.dst_text or "" for r in page.ordered()]):\n'
     '        if n not in names:\n'
     '            names.append(n)',
     '    pass', T_NAME),
    ("name-the-list-is-never-sent", TR,
     '        out["names"] = names[-60:]', '        pass', T_NAME),
    ("name-the-cap-keeps-the-oldest", TR,
     '        out["names"] = names[-60:]',
     '        out["names"] = names[:60]', T_NAME),
    ("drift-the-prose-is-never-checked", TR,
     '            for was, now in name_drift(was_said, names_in(r.dst_text or "")):',
     '            for was, now in []:', T_NAME),
    ("drift-it-is-read-after-this-page-is-folded-in", TR,
     '        was_said = list(getattr(ctx, "names_seen", None) or [])',
     '        remember_said(ctx, page, {})\n'
     '        was_said = list(getattr(ctx, "names_seen", None) or [])', T_NAME),
    ("drift-only-a-project-keeping-a-story-is-checked", TR,
     '        was_said = list(getattr(ctx, "names_seen", None) or [])',
     '        was_said = (list(getattr(ctx, "names_seen", None) or [])'
     ' if story else [])', T_NAME),
    ("person-any-length-of-name-is-a-person", TR,
     '    if len(parts) != 2:\n        return ""',
     '    if not parts:\n        return ""', T_NAME),
    ("person-a-shared-surname-is-enough", TR,
     '        if first and first[0].lower() == parts[0].lower() \\\n',
     '        if first and parts[0].lower() in [x.lower() for x in first] \\\n',
     T_NAME),
    ("person-a-place-named-after-somebody-is-a-person", TR,
     '    if any(len(p) < 3 or not p[0].isupper() or _bare(p) != p\n'
     '           or not p.isalpha() for p in parts):\n'
     '        return ""',
     '    if False:\n        return ""', T_NAME),
    ("person-the-glossary-takes-anybody", TR,
     '        who = is_a_person(name, characters)\n        if who:',
     '        who = is_a_person(name, characters)\n        if False:', T_NAME),
    ("person-the-gate-is-never-told-who-the-cast-are", TR,
     '            gl_refused = merge_glossary(ctx.glossary, gl,\n'
     '                                        getattr(ctx, "characters", None))',
     '            gl_refused = merge_glossary(ctx.glossary, gl)', T_NAME),
    # ---- the dash at the front of a bubble
    ("dash-a-plain-hyphen-is-not-a-dash-again", TR,
     '{_OPENERS})[-\u2014\u2013]+\\s*"',
     '{_OPENERS})[\u2014\u2013]+\\s*"', T_DASH2),
    ("dash-the-source-having-one-keeps-the-leading-one", TR,
     '    t = _EDGE_LEAD.sub(r"\\1", t, count=1)\n'
     '    if source_has_dash(src):\n'
     '        return t.strip() or dst',
     '    if source_has_dash(src):\n'
     '        return dst\n'
     '    t = _EDGE_LEAD.sub(r"\\1", t, count=1)', T_DASH2),
    ("dash-a-word-cut-off-mid-hyphen-loses-it", TR,
     '(?:\\s*[\u2014\u2013]+|\\s+-+)(', '(?:\\s*[\u2014\u2013]+|\\s*-+)(', T_DASH2),
    # ---- two sound effects in one box
    ("twofx-the-box-never-comes-apart", CTD,
     "                    got = _two_effects_in(cores)",
     "                    got = None", T_TWOFX),
    ("twofx-any-gap-is-a-break", CTD,
     "SPLIT_GAP = 0.60", "SPLIT_GAP = 0.05", T_TWOFX),
    ("twofx-no-gap-is-ever-a-break", CTD,
     "SPLIT_GAP = 0.60", "SPLIT_GAP = 2.50", T_TWOFX),
    ("twofx-a-speck-counts-as-an-effect", CTD,
     "SPLIT_ALIKE = 0.35", "SPLIT_ALIKE = 0.05", T_TWOFX),
    ("twofx-two-characters-are-split-too", CTD,
     "SPLIT_LEAST = 3", "SPLIT_LEAST = 2", T_TWOFX),
    ("twofx-the-sides-are-never-sized", CTD,
     "    if min(big) < SPLIT_ALIKE * max(big):\n        return None",
     "    if False:\n        return None", T_TWOFX),
    ("twofx-the-gap-is-not-scaled-by-the-character", CTD,
     "    return ((gx * gx + gy * gy) ** 0.5) / max(1, s)",
     "    return (gx * gx + gy * gy) ** 0.5", T_TWOFX),
    ("twofx-the-widest-link-is-a-span-not-a-step", CTD,
     "    edges.sort(key=lambda t: t[0])\n    par = list(range(n))",
     "    edges.sort(key=lambda t: -t[0])\n    par = list(range(n))", T_TWOFX),
    ("twofx-a-character-just-outside-is-dropped", CTD,
     "        if gx0 >= x - 6 and gx1 <= x + w + 6 \\\n"
     "                and gy0 >= y - 6 and gy1 <= y + h + 6:",
     "        if gx0 >= x and gx1 <= x + w \\\n"
     "                and gy0 >= y and gy1 <= y + h:", T_TWOFX),
    ("twofx-dialogue-is-split-as-well", CTD,
     '                if _kinds.family_of(r.kind) == "sfx":',
     "                if True:", T_TWOFX),
    # ---- the big sound effects the cleaner cannot put back
    # The rule is CALLED. `detect` is what the browser reaches, and it needs
    # a page and the weights to run, so this is measured on the one thing a
    # unit test can hold: the line is there and it is not conditional on
    # anything else. The behaviour of the rule itself is the six below.
    ("bigfx-the-rule-is-never-called", PRJ,
     "        if no_big_sfx:\n"
     "            im = page.image\n"
     "            found = big_sfx(found,\n"
     "                            im.shape[1] if im is not None else 0)",
     "        pass", T_SFXTICK),
    ("bigfx-the-bar-drops-to-200px", PRJ,
     "BIG_SFX = 300 / 690", "BIG_SFX = 200 / 690", T_SFXTICK),
    ("bigfx-nothing-is-ever-big-enough", PRJ,
     "BIG_SFX = 300 / 690", "BIG_SFX = 900 / 690", T_SFXTICK),
    ("bigfx-the-bar-is-taken-against-the-height", PRJ,
     "                            im.shape[1] if im is not None else 0)",
     "                            im.shape[0] if im is not None else 0)",
     T_SFXTICK),
    ("bigfx-only-the-height-counts-not-the-longest-side", PRJ,
     "        big = max(bb[2], bb[3]) >= bar",
     "        big = bb[3] >= bar", T_SFXTICK),
    ("bigfx-only-the-width-counts", PRJ,
     "        big = max(bb[2], bb[3]) >= bar",
     "        big = bb[2] >= bar", T_SFXTICK),
    ("bigfx-every-kind-is-cut-not-only-effects", PRJ,
     '        if big and group_of(getattr(r, "kind", "")) == "sfx":',
     "        if big:", T_SFXTICK),
    ("bigfx-a-page-of-no-size-drops-everything", PRJ,
     "    if not page_width or share <= 0:\n        return list(found)",
     "    if False:\n        return list(found)", T_SFXTICK),
    ("bigfx-the-endpoint-reads-absent-as-off", ED,
     '                nobig = body.get("no_big_sfx") is not False',
     '                nobig = body.get("no_big_sfx") is True', T_SFXTICK),
    ("bigfx-the-default-is-off-in-the-signature", PRJ,
     "               no_big_sfx: bool = True) -> None:",
     "               no_big_sfx: bool = False) -> None:", T_SFXTICK),
    ("bigfx-the-sub-tick-starts-unticked", HTM,
     '        <input type="checkbox" id="kSfxBig" checked>',
     '        <input type="checkbox" id="kSfxBig">', T_SFXTICK),
    ("bigfx-one-route-forgets-to-send-it", JS,
     "    await api('/api/detect_all','POST',{kinds, pages:[cur],"
     " no_big_sfx:noBig});",
     "    await api('/api/detect_all','POST',{kinds, pages:[cur]});",
     T_SFXTICK),

    # ---- CRAFT gets the CPU's fast path. 93% of Find text lives in one net,
    # and the only saving that does not cost a box is the memory layout its
    # weights are stored in.
    ("cpufast-the-layout-is-never-asked-for", CRA,
     "        lay_out_for_the_cpu(r)\n", "", T_CPUFAST),
    ("cpufast-the-weights-are-put-back-the-slow-way", CRA,
     "        reader.detector.to(memory_format=torch.channels_last)",
     "        reader.detector.to(memory_format=torch.contiguous_format)",
     T_CPUFAST),
    ("cpufast-it-is-laid-out-again-on-every-page", CRA,
     "        lay_out_for_the_cpu(r)\n"
     "        _readers[langs] = r\n"
     "    return _readers[langs]",
     "        _readers[langs] = r\n"
     "    lay_out_for_the_cpu(_readers[langs])\n"
     "    return _readers[langs]", T_CPUFAST),
    ("cpufast-a-torch-that-refuses-takes-find-text-down", CRA,
     "    try:\n"
     "        import torch\n"
     "        reader.detector.to(memory_format=torch.channels_last)\n"
     "    except Exception:\n"
     "        pass",
     "    import torch\n"
     "    reader.detector.to(memory_format=torch.channels_last)", T_CPUFAST),
    ("cpufast-the-reader-is-rebuilt-every-call", CRA,
     "    if langs not in _readers:\n        import easyocr",
     "    if True:\n        import easyocr", T_CPUFAST),
    # The saving that was refused, and the test that refuses it. Lowering the
    # canvas is the biggest number available in Find text and it is paid for
    # in lost boxes -- 029 comes back with 6 of its 8.
    ("cpufast-the-canvas-is-lowered-for-the-2x", CRA,
     "CANVAS = 2560", "CANVAS = 1600", T_CPUFAST),
    ("cpufast-the-canvas-drifts-a-little", CRA,
     "CANVAS = 2560", "CANVAS = 2048", T_CPUFAST),
    ("cpufast-the-page-is-magnified-first", CRA,
     "MAG_RATIO = 1.0", "MAG_RATIO = 1.5", T_CPUFAST),

    # ---- A box with nothing in it.
    ("nothing-the-empty-box-is-exempt-again", CTD,
     "    # under any threshold.\n"
     "    n, _lab, st, _c = cv2.connectedComponentsWithStats(ink, 8)",
     "    # under any threshold.\n"
     "    if not ink.any():\n        return False\n"
     "    n, _lab, st, _c = cv2.connectedComponentsWithStats(ink, 8)",
     T_NOTHING),
    ("nothing-an-empty-box-is-kept-by-the-mark-count", CTD,
     "    if marks > STRAY_PIECES:\n        return False",
     "    if marks >= STRAY_PIECES:\n        return False", T_NOTHING),
    ("nothing-the-fill-is-never-under-anything", CTD,
     "    return fill < fill_under", "    return fill <= 0.0", T_NOTHING),
    ("nothing-a-tiny-box-is-judged-after-all", CTD,
     "    if (x1 - x0) * (y1 - y0) < 400:\n        return False", "",
     T_NOTHING),
    ("nothing-the-sweep-runs-on-manga-too", CTD,
     '        "stray_fill": None,\n', '        "stray_fill": 0.115,\n',
     T_NOTHING),

    # ---- A balloon of any colour.
    ("colour-the-pass-runs-with-no-weights", CBU,
     "    if not path or not os.path.isfile(path):\n        return False",
     "    if False:\n        return False", T_COLOUR),
    ("colour-it-overrules-the-measurement", CBU,
     '        if getattr(r, "bubble_mask", None) is not None:\n            continue\n',
     "", T_COLOUR),
    ("colour-a-sound-effect-is-made-dialogue", CBU,
     '        if _kinds.family_of(getattr(r, "kind", "bubble")) == "sfx":\n'
     "            continue\n", "", T_COLOUR),
    ("colour-a-balloon-that-holds-none-of-it-still-counts", CBU,
     "HOLDS = 0.90", "HOLDS = 0.0", T_COLOUR),
    ("colour-a-balloon-the-size-of-the-writing-counts", CBU,
     "GAIN = 1.15", "GAIN = 1.0", T_COLOUR),
    ("colour-the-biggest-balloon-wins-instead", CBU,
     "            if best is None or area < (best[2] - best[0]) * (best[3] - best[1]):",
     "            if best is None or area > (best[2] - best[0]) * (best[3] - best[1]):",
     T_COLOUR),
    ("colour-half-the-page-is-a-balloon", CBU,
     "MAX_PAGE = 0.45", "MAX_PAGE = 0.99", T_COLOUR),
    ("colour-a-tall-page-is-read-in-one-go", CBU,
     "    if h <= w * TALL:\n        return [(0, h)]",
     "    if True:\n        return [(0, h)]", T_COLOUR),
    ("colour-the-windows-do-not-overlap", CBU,
     "OVERLAP = 0.2", "OVERLAP = 0.0", T_COLOUR),
    ("colour-only-the-first-colour-is-tried", CBU,
     "        if len(out) == 2:\n            break",
     "        if len(out) == 1:\n            break", T_COLOUR),
    ("colour-a-shape-of-anything-is-a-balloon", CBU,
     "SOLID = 0.55", "SOLID = 0.0", T_COLOUR),
    ("colour-a-fill-that-runs-on-is-a-balloon", CBU,
     "    return float((d[out] <= TONE).mean()) <= SPILLS", "    return True",
     T_COLOUR),
    ("colour-the-shape-need-not-beat-the-writing", CBU,
     "        if float(got.sum()) < GAIN * max(1.0, float(tw * th)):\n"
     "            continue\n", "", T_COLOUR),
    ("colour-the-letters-are-left-as-holes", CBU,
     "    piece[inv == 1] = 1", "    pass", T_COLOUR),
    ("colour-a-sub-type-is-overwritten", CBU,
     '        if _kinds.family_of(getattr(r, "kind", "bubble")) != "bubble":\n'
     '            r.kind = "bubble"',
     '        r.kind = "bubble"', T_COLOUR),
    ("colour-find-text-never-calls-it", CTD,
     "        _CB.name_the_balloons(img, regions, bubble_weights)", "",
     T_COLOUR),
    ("colour-it-runs-before-the-measurement", CTD,
     "    from .balloon import attach_balloons\n    attach_balloons(gray, regions)",
     "    from .balloon import attach_balloons", T_COLOUR),
    ("colour-a-named-file-that-is-gone-is-used-anyway", PRJ_PY,
     "            return named if os.path.isfile(named) else \"\"",
     "            return named", T_COLOUR),

    # ---- ...and what each box IS.
    ("word-the-model-never-gets-a-say", CTD,
     "        _CB.name_the_kinds(img, regions, bubble_weights, boxes=cb_boxes)",
     "        pass", T_COLOUR),
    ("word-it-is-asked-before-the-measuring", CTD,
     "    if bubble_weights and cb_boxes:\n"
     "        from . import comicbubble as _CB\n"
     "        _CB.name_the_kinds(img, regions, bubble_weights, boxes=cb_boxes)\n",
     "", T_COLOUR),
    ("word-a-sound-effect-is-relabelled-too", CBU,
     '        if kind not in ("bubble", "freefloat"):\n            continue',
     "        if False:\n            continue", T_COLOUR),
    ("word-a-guess-is-as-good-as-a-certainty", CBU,
     "SURE = 0.50", "SURE = 0.0", T_COLOUR),
    ("word-nothing-is-ever-sure-enough", CBU,
     "SURE = 0.50", "SURE = 0.999", T_COLOUR),
    ("word-a-box-it-barely-touches-still-votes", CBU,
     "SAYS_OVER = 0.35", "SAYS_OVER = 0.0", T_COLOUR),
    ("word-the-two-classes-are-swapped", CBU,
     '        want = "bubble" if best[4] == 1 else "freefloat"',
     '        want = "freefloat" if best[4] == 1 else "bubble"', T_COLOUR),
    ("word-the-balloon-boxes-vote-as-well", CBU,
     "    said = [b for b in boxes if b[4] in (1, 2)]",
     "    said = [b for b in boxes if b[4] in (0, 1, 2)]", T_COLOUR),
    ("word-the-first-box-wins-instead-of-the-best", CBU,
     "            if o > over:\n                best, over = b, o",
     "            if best is None:\n                best, over = b, o", T_COLOUR),
    ("word-the-net-is-run-twice", CTD,
     "        _CB.name_the_kinds(img, regions, bubble_weights, boxes=cb_boxes)",
     "        _CB.name_the_kinds(img, regions, bubble_weights)", T_COLOUR),

    # ---- no effects wanted, no second detector.
    ("nofx-the-tick-is-ignored", CTD,
     "    if craft_x and craft_y and want_sfx:",
     "    if craft_x and craft_y:", T_NOFX),
    ("nofx-the-tick-alone-decides", CTD,
     "    if craft_x and craft_y and want_sfx:",
     "    if want_sfx:", T_NOFX),
    ("nofx-it-runs-only-when-nobody-asked", CTD,
     "    if craft_x and craft_y and want_sfx:",
     "    if craft_x and craft_y and not want_sfx:", T_NOFX),
    ("nofx-the-default-is-off", CTD,
     "                     want_sfx: bool = True",
     "                     want_sfx: bool = False", T_NOFX),
    ("nofx-the-project-never-passes-it", PRJ_PY,
     '                want_sfx=("sfx" in kinds),\n', "", T_NOFX),
    ("nofx-the-project-passes-the-wrong-tick", PRJ_PY,
     '                want_sfx=("sfx" in kinds),',
     '                want_sfx=("bubble" in kinds),', T_NOFX),

    # ---- a box the reader found nothing in
    ("blank-the-sweep-never-runs", ED_PY,
     '    if p.settings.get("drop_empty") is not False:',
     "    if False:", T_BLANK),
    ("blank-an-outage-empties-the-page", ED_PY,
     "    if len(empty) == len(live):\n"
     "        return []            # the reader had an outage, not a page of bad boxes\n",
     "", T_BLANK),
    ("blank-a-locked-box-is-thrown-out-too", ED_PY,
     "            and not getattr(r, \"locked\", False)\n", "", T_BLANK),
    ("blank-a-box-somebody-typed-is-thrown-out-too", ED_PY,
     '            if not getattr(r, "own_text", False)\n',
     "            if True\n", T_BLANK),
    ("blank-a-translated-box-is-thrown-out-too", ED_PY,
     '            and not (getattr(r, "dst_text", "") or "").strip()]',
     "            ]", T_BLANK),
    ("blank-whitespace-counts-as-text", ED_PY,
     '    empty = [r for r in live if not (getattr(r, "src_text", "") or "").strip()]',
     '    empty = [r for r in live if not (getattr(r, "src_text", "") or "")]',
     T_BLANK),
    ("blank-the-setting-is-off-by-default", PRJ_PY,
     '            "drop_empty": True,', '            "drop_empty": False,',
     T_BLANK),

    # ---- painted lettering is not dialogue
    ("paint-the-rays-escape-is-never-vetoed", CTD,
     "                if _ring_rays(gray, r.bbox) >= RAYS_DENS \\\n"
     "                        and _ink_chroma(img, r.bbox) < INK_CHROMA:",
     "                if _ring_rays(gray, r.bbox) >= RAYS_DENS:", T_PAINT),
    ("paint-the-floor-escape-is-never-vetoed", CTD,
     "            elif _paper_under(gray, r.bbox, r.text_mask)"
     " >= UNDER_PAPER \\\n"
     "                    and _ink_chroma(img, r.bbox) < INK_CHROMA:",
     "            elif _paper_under(gray, r.bbox, r.text_mask)"
     " >= UNDER_PAPER:", T_PAINT),
    ("paint-the-veto-runs-the-wrong-way", CTD,
     "                        and _ink_chroma(img, r.bbox) < INK_CHROMA:",
     "                        and _ink_chroma(img, r.bbox) >= INK_CHROMA:",
     T_PAINT),
    ("paint-the-floor-veto-runs-the-wrong-way", CTD,
     "            elif _paper_under(gray, r.bbox, r.text_mask)"
     " >= UNDER_PAPER \\\n"
     "                    and _ink_chroma(img, r.bbox) < INK_CHROMA:",
     "            elif _paper_under(gray, r.bbox, r.text_mask)"
     " >= UNDER_PAPER \\\n"
     "                    and _ink_chroma(img, r.bbox) >= INK_CHROMA:",
     T_PAINT),
    ("paint-nothing-is-ever-coloured-enough", CTD,
     "INK_CHROMA = 12.0", "INK_CHROMA = 300.0", T_PAINT),
    ("paint-everything-counts-as-coloured", CTD,
     "INK_CHROMA = 12.0", "INK_CHROMA = 0.0", T_PAINT),
    ("paint-the-bar-is-under-the-ink-it-must-keep", CTD,
     "INK_CHROMA = 12.0", "INK_CHROMA = 0.5", T_PAINT),
    ("paint-the-ground-is-whichever-side-is-smaller", CTD,
     "    ink = (~d if d[edge].mean() > 0.5 else d).astype(np.uint8)",
     "    ink = (d if d.mean() <= 0.5 else ~d).astype(np.uint8)", T_PAINT),
    ("paint-the-ground-is-always-the-light-side", CTD,
     "    ink = (~d if d[edge].mean() > 0.5 else d).astype(np.uint8)",
     "    ink = d.astype(np.uint8)", T_PAINT),
    ("paint-the-whole-glyph-is-averaged-not-its-core", CTD,
     "    core = dt >= max(1.0, 0.5 * float(np.percentile(dt[ink > 0], 90)))",
     "    core = ink > 0", T_PAINT),
    ("paint-the-core-is-a-fixed-width-whatever-the-stroke", CTD,
     "    core = dt >= max(1.0, 0.5 * float(np.percentile(dt[ink > 0], 90)))",
     "    core = dt >= 1.0", T_PAINT),
    ("paint-chroma-is-measured-off-lightness", CTD,
     "    a = lab[..., 1].astype(np.float32) - 128.0\n"
     "    b = lab[..., 2].astype(np.float32) - 128.0",
     "    a = lab[..., 0].astype(np.float32) - 128.0\n"
     "    b = lab[..., 0].astype(np.float32) - 128.0", T_PAINT),
    ("paint-chroma-is-not-centred-on-neutral", CTD,
     "    a = lab[..., 1].astype(np.float32) - 128.0\n"
     "    b = lab[..., 2].astype(np.float32) - 128.0",
     "    a = lab[..., 1].astype(np.float32)\n"
     "    b = lab[..., 2].astype(np.float32)", T_PAINT),
    ("paint-an-empty-box-is-loudly-coloured", CTD,
     "    if int(ink.sum()) < CHROMA_MIN_INK:\n        return 0.0",
     "    if int(ink.sum()) < CHROMA_MIN_INK:\n        return 999.0", T_PAINT),
    ("paint-a-box-of-nothing-is-still-measured", CTD,
     "    if (x1 - x0) * (y1 - y0) < CHROMA_MIN_BOX:\n        return 0.0",
     "    if False:\n        return 0.0", T_PAINT),
    ("paint-the-border-is-the-whole-box", CTD,
     "CHROMA_FRAME = 2", "CHROMA_FRAME = 10000", T_PAINT),

    # A box only comic-text-detector believes in has to show its letters.
    # See `dbcoo.SFX_GLYPHS` -- eleven of the fifteen junk boxes on the
    # chapter are one cell of one table, and this is the rule over that cell.
    ("bodies-the-rule-is-quietly-off", DBCOO,
     "SFX_GLYPHS = 5 ", "SFX_GLYPHS = 0 ", T_BODIES),
    ("bodies-one-mark-is-a-line-of-writing", DBCOO,
     "SFX_GLYPHS = 5 ", "SFX_GLYPHS = 1 ", T_BODIES),
    ("bodies-nothing-is-ever-enough-letters", DBCOO,
     "SFX_GLYPHS = 5 ", "SFX_GLYPHS = 10000 ", T_BODIES),
    ("bodies-the-balloon-arm-is-back-on", DBCOO,
     "SFX_KEEP_WALLED = False ", "SFX_KEEP_WALLED = True ", T_BODIES),
    ("bodies-a-speck-of-tone-is-a-character", DBCOO,
     "SFX_GLYPH_AREA = 40 ", "SFX_GLYPH_AREA = 1 ", T_BODIES),
    ("bodies-no-mark-is-ever-big-enough", DBCOO,
     "SFX_GLYPH_AREA = 40 ", "SFX_GLYPH_AREA = 100000 ", T_BODIES),
    ("bodies-the-floor-is-a-strict-one", DBCOO,
     "                   if int(st[i, cv2.CC_STAT_AREA]) >= min_area))",
     "                   if int(st[i, cv2.CC_STAT_AREA]) > min_area))",
     T_BODIES),
    ("bodies-the-background-counts-as-a-character", DBCOO,
     "    return int(sum(1 for i in range(1, n)",
     "    return int(sum(1 for i in range(0, n)", T_BODIES),
    ("bodies-a-missing-mask-is-full-of-writing", DBCOO,
     "    if tmask is None:\n        return 0\n",
     "    if False:\n        return 0\n", T_BODIES),
    ("bodies-the-whole-page-is-counted-not-the-box", DBCOO,
     "    m = (tmask[y0:y1, x0:x1] > 0).astype(np.uint8)\n"
     "    if not m.any():\n        return 0",
     "    m = (tmask > 0).astype(np.uint8)\n"
     "    if not m.any():\n        return 0", T_BODIES),
    ("bodies-a-box-off-the-left-edge-reads-the-right-one", DBCOO,
     "    x0, y0 = max(0, x0), max(0, y0)\n"
     "    m = (tmask[y0:y1, x0:x1] > 0).astype(np.uint8)",
     "    m = (tmask[y0:y1, x0:x1] > 0).astype(np.uint8)", T_BODIES),
    ("bodies-the-route-keeps-its-own-copy-of-the-bar", DBCOO,
     "                   glyphs: int = SFX_GLYPHS, split_texts: bool "
     "= SPLIT_TEXTS,",
     "                   glyphs: int = 0, split_texts: bool = SPLIT_TEXTS,",
     T_BODIES),

    # The balloon outranks the specialist, and a rectangle round two effects
    # is not one box. See `tests/test_the_balloon_outranks_the_specialist.py`.
    ("weld-the-manga-route-skips-the-effects-again", CTD,
     "        if (skip_sfx and _kinds.family_of(r.kind) == \"sfx\") \\\n"
     "                or r.text_mask is None:",
     "        if _kinds.family_of(r.kind) == \"sfx\" or r.text_mask is None:",
     T_WELD),
    ("weld-every-effect-is-split-on-the-manhwa-too", CTD,
     "def _each_text_its_own_box(regions: list, skip_sfx: bool = True)",
     "def _each_text_its_own_box(regions: list, skip_sfx: bool = False)",
     T_WELD),
    ("weld-the-text-split-is-off", DBCOO,
     "SPLIT_TEXTS = True", "SPLIT_TEXTS = False", T_WELD),
    ("weld-the-effect-split-is-off", DBCOO,
     "SPLIT_SFX = True", "SPLIT_SFX = False", T_WELD),
    ("weld-a-grazing-effect-counts-as-one-inside", DBCOO,
     "SFX_PIECE_IN = 0.60", "SFX_PIECE_IN = 0.0", T_WELD),
    ("weld-no-effect-is-ever-inside-anything", DBCOO,
     "SFX_PIECE_IN = 0.60", "SFX_PIECE_IN = 1.01", T_WELD),
    ("weld-the-route-splits-behind-the-switch", DBCOO,
     "                   split_sfx: bool = SPLIT_SFX, **tuning) -> list:",
     "                   split_sfx: bool = False, **tuning) -> list:", T_WELD),
    ("weld-the-text-split-runs-behind-the-switch", DBCOO,
     "split_texts: bool = SPLIT_TEXTS,\n"
     "                   split_sfx: bool = SPLIT_SFX,",
     "split_texts: bool = False,\n"
     "                   split_sfx: bool = SPLIT_SFX,", T_WELD),
    ("weld-the-effect-family-is-labelled-like-the-rest", DBCOO,
     "    if _kinds.family_of(kind) == \"sfx\":\n        return \"sfx\"",
     "    if False:\n        return \"sfx\"", T_WELD),
    ("weld-a-fitted-balloon-does-not-outrank-the-specialist", DBCOO,
     "    if fitted:\n        return \"bubble\"\n"
     "    if _kinds.family_of(kind) == \"sfx\":",
     "    if _kinds.family_of(kind) == \"sfx\":", T_WELD),
    ("weld-an-effect-is-promoted-by-any-wall-at-all", DBCOO,
     "    if fitted:\n        return \"bubble\"",
     "    if fitted or wall():\n        return \"bubble\"", T_WELD),
    ("weld-the-walls-are-always-measured", DBCOO,
     "    if wall() or enclosed():", "    if any([wall(), enclosed()]):",
     T_WELD),
    ("weld-nothing-round-the-writing-is-still-dialogue", DBCOO,
     "    return \"freefloat\"", "    return \"bubble\"", T_WELD),

    # The Manga109 segmenter. See `tests/test_the_manga109_segmenter.py`.
    ("seg-the-page-is-read-at-the-wrong-size", SEG,
     "SIZE = 1024", "SIZE = 640", T_SEG),
    ("seg-panels-are-carried-around-too", SEG,
     "want: tuple = (TEXT, BALLOON)", "want: tuple = (TEXT, BALLOON, FRAME)",
     T_SEG),
    ("seg-the-classes-are-guessed-by-number", SEG,
     'TEXT = "text"', 'TEXT = "0"', T_SEG),
    ("seg-a-missing-wheel-is-left-to-explode", SEG,
     "    try:\n        import ultralytics  # noqa: F401\n    except Exception:",
     "    if False:", T_SEG),
    ("seg-no-weights-is-not-worth-saying", SEG,
     '        return "no Manga109 segmenter weights are set"',
     '        return ""', T_SEG),
    ("seg-a-path-that-is-not-there-is-fine", SEG,
     '        return "Manga109 segmenter weights are not at %s" % path',
     '        return ""', T_SEG),
    ("seg-writing-barely-touching-a-balloon-is-inside-it", DBCOO,
     "IN_BALLOON = 0.60", "IN_BALLOON = 0.0", T_SEG),
    ("seg-nothing-is-ever-inside-a-balloon", DBCOO,
     "IN_BALLOON = 0.60", "IN_BALLOON = 1.01", T_SEG),
    ("seg-the-margins-are-left-empty", DBCOO,
     "FILL_GAPS = True", "FILL_GAPS = False", T_SEG),
    ("seg-the-margins-are-filled-with-anything-at-all", DBCOO,
     "            if glyph_bodies(tmask, b) < glyphs:\n                continue",
     "            if False:\n                continue", T_SEG),
    ("seg-the-detector-runs-twice-again", DBCOO,
     "    tmask = getattr(page, \"seg_mask\", None)\n    if tmask is None:\n"
     "        tmask = CT.page_text_mask(",
     "    if True:\n        tmask = CT.page_text_mask(", T_SEG),
    ("seg-the-route-keeps-its-own-balloon-bar", DBCOO,
     "                inside: float = IN_BALLOON,",
     "                inside: float = 0.9,", T_SEG),
    ("seg-it-is-on-by-default", PRJ,
     '            "manga_segmenter": False,', '            "manga_segmenter": True,',
     T_SEG),
    ("seg-a-manhwa-is-offered-it-too", PRJ,
     "        if self.medium not in self.TWO_MEDIA:\n"
     "            return (\"this was measured on manga and only on manga -- see \"\n"
     "                    \"Project.TWO_MEDIA\")\n"
     "        if not (self.settings.get(\"weights\") or \"\"):\n"
     "            return \"comic-text-detector weights are needed for the clean mask\"",
     "        if not (self.settings.get(\"weights\") or \"\"):\n"
     "            return \"comic-text-detector weights are needed for the clean mask\"",
     T_SEG),
    ("seg-the-clean-mask-is-not-required", PRJ,
     '        if not (self.settings.get("weights") or ""):\n'
     '            return "comic-text-detector weights are needed for the clean mask"',
     "        if False:\n            return \"\"", T_SEG),
    ("seg-a-broken-checkpoint-still-switches-it-on", PRJ,
     "        return not self.why_not_manga_segmenter()", "        return True",
     T_SEG),

    # One detector finds all of it, and a box round other boxes is a bracket.
    # The default BECAME True on purpose (test_one_detector_finds_all_of_it
    # pins it), so the mutant is the reverse of what it was: quietly turning
    # the route OFF is now the bug a test must catch. The old spelling of
    # this spec also taught the leftover-mutant guard a lesson: with the
    # find string legitimately gone and the replacement legitimately present
    # once, a healthy tree read as a crime scene and every measurement in
    # the project stopped.
    ("anim-the-route-is-off-by-default", PRJ,
     '            "animetext": True,', '            "animetext": False,',
     T_ANIM),
    ("anim-a-missing-checkpoint-does-not-stop-it", PRJ,
     "        return not self.why_not_animetext()", "        return True",
     T_ANIM),
    ("anim-a-manhwa-is-offered-it-too", PRJ,
     '        if self.medium not in self.TWO_MEDIA:\n'
     '            return ("this was measured on manga and only on manga -- see "\n'
     '                    "Project.TWO_MEDIA")\n'
     '        if not (self.settings.get("weights") or ""):\n'
     '            return "comic-text-detector weights are needed for the clean mask"\n'
     "        from .detect import animetext as _at",
     '        if not (self.settings.get("weights") or ""):\n'
     '            return "comic-text-detector weights are needed for the clean mask"\n'
     "        from .detect import animetext as _at", T_ANIM),
    ("anim-the-clean-mask-is-not-required", PRJ,
     '        if not (self.settings.get("weights") or ""):\n'
     '            return "comic-text-detector weights are needed for the '
     'clean mask"\n'
     "        from .detect import animetext as _at",
     "        from .detect import animetext as _at", T_ANIM),
    ("anim-the-downloaded-filename-is-not-accepted", PRJ,
     '                            "yolo12l_animetext.pt", "model.pt")',
     '                            "yolo12l_animetext.pt")', T_ANIM),
    ("anim-the-page-is-read-at-the-wrong-size", ANIM,
     "SIZE = 1024", "SIZE = 640", T_ANIM),
    ("anim-the-class-is-guessed-by-number", ANIM,
     'TEXT = "text_block"', 'TEXT = "0"', T_ANIM),
    ("anim-a-missing-wheel-is-left-to-explode", ANIM,
     "    try:\n        import ultralytics  # noqa: F401\n"
     "    except Exception:\n"
     '        return ("ultralytics is not installed -- run `pip install "\n'
     '                "ultralytics` (the AnimeText model needs it)")',
     "    pass", T_ANIM),
    ("anim-no-weights-is-not-worth-saying", ANIM,
     '    if not path:\n        return "no AnimeText weights are set"',
     '    if not path:\n        return ""', T_ANIM),
    ("anim-the-bracket-is-kept", DBCOO,
     "        if held >= least:\n            continue",
     "        if False:\n            continue", T_ANIM),
    ("anim-a-duplicate-pair-is-read-as-a-bracket", DBCOO,
     "NEST_LEAST = 2", "NEST_LEAST = 1", T_ANIM),
    ("anim-anything-nearby-counts-as-held", DBCOO,
     "NEST_IN = 0.70", "NEST_IN = 0.0", T_ANIM),
    ("anim-nothing-is-ever-held", DBCOO,
     "NEST_IN = 0.70", "NEST_IN = 1.01", T_ANIM),
    ("anim-the-bigger-box-is-the-one-kept", DBCOO,
     "            if area_q < area_b and _share(q, b) > inside:",
     "            if area_q > area_b and _share(q, b) > inside:", T_ANIM),
    ("anim-a-box-of-equal-size-counts-as-held", DBCOO,
     "            if area_q < area_b and _share(q, b) > inside:",
     "            if area_q <= area_b and _share(q, b) > inside:", T_ANIM),
    ("anim-the-route-keeps-its-own-bracket-bar", DBCOO,
     "                     drop_nested: float = NEST_IN, **tuning) -> list:",
     "                     drop_nested: float = 0.7, **tuning) -> list:",
     T_ANIM),
    ("anim-the-sound-effect-model-is-required", DBCOO,
     '                     coo_ckpt: str = "", classify: bool = True,',
     '                     coo_ckpt: str, classify: bool = True,', T_ANIM),

    # The licence, and the list of what the app can load. lee: *"the software
    # itself willmbe free"*, and free with nothing written down is
    # all-rights-reserved.
    ("lic-the-reason-for-the-licence-is-not-recorded", NOTICE,
     "comic-text-detector\n  file      comictextdetector.pt.onnx",
     "a text detector\n  file      comictextdetector.pt.onnx", T_LIC),
    ("lic-a-model-drops-off-the-list", NOTICE,
     "  file      dbpp_coo.dat / dbpp_coo.pth / DB_finetune_COO",
     "  file      (removed)", T_LIC),
    ("lic-the-weights-are-said-to-ship-with-it", NOTICE,
     "NONE OF THE MODEL FILES ARE REDISTRIBUTED WITH THIS SOFTWARE. Every one"
     " of\nthem is downloaded by the person using it",
     "The model files ship with this software. Every one of\nthem is bundled"
     " by the person building it", T_LIC),
    ("lic-manga109-is-not-mentioned-at-all", NOTICE,
     "MANGA109, WHICH IS NOT A SOFTWARE LICENCE",
     "A NOTE ON TRAINING DATA", T_LIC),
    ("lic-manga109-is-presented-as-settled", NOTICE,
     "is not settled law anywhere", "is settled law", T_LIC),
    ("lic-the-remote-engines-are-called-code", NOTICE,
     "are services, not code in this program",
     "are code in this program", T_LIC),
    ("lic-it-claims-to-be-legal-advice", NOTICE,
     "It is not legal advice and nobody here is a lawyer.",
     "This is a complete answer.", T_LIC),
    ("lic-the-unchecked-cards-are-given-an-answer", NOTICE,
     "  licence   check the model card before relying on it -- not stated at"
     " the\n            time this file was written",
     "  licence   MIT", T_LIC),

    # Naming a box from what was read out of it, instead of from a second net.
    ("read-the-balloon-no-longer-outranks-the-text", RK,
     '    if in_balloon:\n        return "bubble"',
     '    if False:\n        return "bubble"', T_RK),
    ("read-an-empty-box-is-speech", RK,
     "    if not text:\n        return True",
     "    if not text:\n        return False", T_RK),
    ("read-a-box-of-punctuation-is-speech", RK,
     "    if not bare:\n        return True",
     "    if not bare:\n        return False", T_RK),
    ("read-kanji-does-not-settle-it", RK,
     "    if KANJI.search(bare):\n        return False",
     "    if False:\n        return False", T_RK),
    ("read-grammar-does-not-settle-it", RK,
     "    if any(c in PARTICLES or c in ENDINGS for c in bare):\n"
     "        return False",
     "    if False:\n        return False", T_RK),
    ("read-only-the-particles-count-not-the-endings", RK,
     "    if any(c in PARTICLES or c in ENDINGS for c in bare):",
     "    if any(c in PARTICLES for c in bare):", T_RK),
    ("read-length-never-settles-it", RK,
     "    if len(bare) > least:\n        return False",
     "    if False:\n        return False", T_RK),
    ("read-anything-of-any-length-is-a-sound", RK,
     "SFX_MAX = 12", "SFX_MAX = 10000", T_RK),
    ("read-nothing-is-ever-short-enough", RK,
     "SFX_MAX = 12", "SFX_MAX = 0", T_RK),
    ("read-the-long-vowel-is-thrown-away-as-punctuation", RK,
     'STRIP = " \\t\\r\\n。、．，!?！？…‥・「」『』（）()〜~-"',
     'STRIP = " \\t\\r\\n。、．，!?！？…‥・「」『』（）()〜~ー-"', T_RK),
    ("read-somebody-elses-own-box-is-relabelled-too", RK,
     '        if getattr(r, "own_text", False):\n            continue',
     "        if False:\n            continue", T_RK),
    ("read-the-move-count-is-always-zero", RK,
     "        moved += (r.kind != was)", "        moved += 0", T_RK),
    ("read-the-ocr-step-relabels-whether-asked-or-not", OCR,
     "             engine_name: str = \"auto\", relabel: bool = False)",
     "             engine_name: str = \"auto\", relabel: bool = True)", T_RK),
    ("read-the-editor-names-boxes-after-it-drops-them", PY,
     '    if p.settings.get("kind_from_text") and p.medium in Project.TWO_MEDIA:',
     '    if False and p.settings.get("kind_from_text"):', T_RK),
    ("read-the-editor-does-it-on-any-format", PY,
     '    if p.settings.get("kind_from_text") and p.medium in Project.TWO_MEDIA:',
     '    if p.settings.get("kind_from_text"):', T_RK),
    ("read-it-is-on-by-default", PRJ,
     '            "kind_from_text": False,', '            "kind_from_text": True,',
     T_RK),

    # Stop means stop, the routes are one choice, and a square selects boxes.
    ("stop-a-cleared-watcher-still-stops", STOPM,
     "    fn = _asked\n    if fn is None:\n        return False",
     "    fn = _asked\n    if fn is None:\n        return True", T_STOP),
    ("stop-check-never-raises", STOPM,
     "    if asked():\n        raise Stopped(\"stopped\")",
     "    if False:\n        raise Stopped(\"stopped\")", T_STOP),
    ("stop-a-broken-watcher-takes-the-run-down", STOPM,
     "    try:\n        return bool(fn())\n    except Exception:\n"
     "        return False",
     "    return bool(fn())", T_STOP),
    ("stop-clear-does-not-clear", STOPM,
     "def clear() -> None:", "def clear_unused() -> None:", T_STOP),
    ("stop-the-ocr-loop-runs-to-the-end", OCR,
     "        _stopping.check()\n        # Somebody's own text box",
     "        # Somebody's own text box", T_STOP),
    ("stop-the-clean-loop-runs-to-the-end", "inpaint.py",
     "        _stopping.check()\n        # sound effects USED to be skipped",
     "        # sound effects USED to be skipped", T_STOP),
    ("stop-the-job-never-hands-the-flag-over", PY,
     "    _stopping.watch(lambda: bool(p.job.get(\"cancel\")))",
     "    pass", T_STOP),
    ("stop-the-flag-is-left-set-for-the-next-run", PY,
     "        _stopping.clear()\n        p.job[\"running\"] = False",
     "        p.job[\"running\"] = False", T_STOP),
    ("stop-a-cancelled-run-is-reported-as-a-crash", PY,
     "    except _stopping.Stopped:", "    except KeyboardInterrupt:", T_STOP),
    ("cards-two-routes-can-be-on-at-once", JSP,
     "  for(const k of ROUTES) proj.settings[k] = (k === name);",
     "  proj.settings[name] = true;", T_STOP),
    ("cards-a-route-with-no-weights-can-be-picked", JSP,
     "  if(name && (!st || !st.ready)) return;", "  if(false) return;", T_STOP),
    ("cards-the-selection-is-read-off-a-dead-checkbox", JSP,
     "    two_specialists:(currentRoute()==='two_specialists'),",
     "    two_specialists:($('two_specialists')\n"
     "                     ? $('two_specialists').checked : false),", T_STOP),
    ("cards-the-estimate-is-per-page-not-per-chapter", JSP,
     "    const secs = sec * (pages || 0);", "    const secs = sec;", T_STOP),
    ("cards-the-rating-is-a-secret", JSP,
     "                 + \' of 226 hand-checked sites right: \' + missed",
     "                 + \' good \' + missed", T_STOP),
    ("boxsel-containment-instead-of-touching", BOXSEL,
     "    if(bx < x1 && bx + bw > x0 && by < y1 && by + bh > y0) out.push(r.id);",
     "    if(bx > x0 && bx + bw < x1 && by > y0 && by + bh < y1) out.push(r.id);",
     T_STOP),
    ("boxsel-s-does-nothing", BOXSEL,
     "  if(e.key === 's' || e.key === 'S'){ toggleBoxSelect(); e.preventDefault(); }",
     "  if(false){ toggleBoxSelect(); e.preventDefault(); }", T_STOP),
    ("boxsel-it-fires-while-you-are-typing", BOXSEL,
     "  if(a && (a.isContentEditable ||\n"
     "           /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName))) return;",
     "  if(false) return;", T_STOP),
    ("boxsel-shift-does-not-add", BOXSEL,
     "  _bsDrag = {x0: p.x, y0: p.y, add: !!(e.shiftKey), el: el};",
     "  _bsDrag = {x0: p.x, y0: p.y, add: false, el: el};", T_STOP),
    # Re-anchored: the disarm moved into the keydown listener when the
    # Escape shortcut was added, and the old anchor's absence (with its
    # replacement present once, as `}` before a listener always is) tripped
    # the leftover-mutant guard on a healthy tree.
    ("boxsel-the-tool-stays-armed", BOXSEL,
     "  else if(e.key === 'Escape' && boxSel) toggleBoxSelect(false);",
     "  else if(false && boxSel) toggleBoxSelect(false);", T_STOP),
    ("merge-one-box-is-enough-to-merge", ROPS,
     "  if(ids.length < 2){ toast('Select two or more boxes to merge.'); return; }",
     "  if(ids.length < 1){ toast('Select two or more boxes to merge.'); return; }",
     T_STOP),
    ("merge-the-first-box-keeps-its-own-rectangle", ROPS,
     "  const x1 = Math.max(...rs.map(r => r.bbox[0] + r.bbox[2]));",
     "  const x1 = rs[0].bbox[0] + rs[0].bbox[2];", T_STOP),
    ("merge-the-old-boxes-are-left-behind", ROPS,
     "  for(const r of rs) await api(`/api/page/${cur}/region/${r.id}`, 'DELETE');",
     "  ;", T_STOP),
    ("merge-no-new-box-is-drawn", ROPS,
     "  const j = await api(`/api/page/${cur}/region`, 'POST', {",
     "  const j = await api(`/api/page/${cur}/region/0`, 'POST', {", T_STOP),
    ("merge-only-the-first-text-survives", ROPS,
     "  const join = (k) => rs.map(r => (r[k] || '').trim()).filter(Boolean).join(' ');",
     "  const join = (k) => (rs[0][k] || '').trim();", T_STOP),
    ("merge-the-order-is-whatever-was-clicked", ROPS,
     "               .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));",
     "               .slice();", T_STOP),
    ("merge-cannot-be-undone-in-one-press", ROPS,
     "  record('region-merge', `${rs.length} boxes merged`,\n"
     "    () => restoreRegions(pg, snaps));",
     "  ;", T_STOP),
    ("merge-the-button-shows-with-nothing-selected", PANELS,
     "        ${selMulti.size>1\n          ? `<button onclick=\"mergeSelected()\"",
     "        ${true\n          ? `<button onclick=\"mergeSelected()\"", T_STOP),
    ("merge-m-always-marks-pixels", SELJS,
     "      if(typeof selMulti!=='undefined' && selMulti.size>1\n"
     "         && typeof mergeSelected==='function') mergeSelected();\n"
     "      else toggleSelTool('rect');",
     "      toggleSelTool('rect');", T_STOP),
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

    # A run killed part-way - a timeout, a Ctrl-C, a `pkill` - never reaches
    # its `finally`, and the mutant it was holding stays on disk. Everything
    # measured afterwards is then measured against it, silently: one such
    # leftover sat in `static/editor.html` for an hour and turned the coin in
    # the top bar into a plain yellow disc.
    #
    # So: before touching anything, look for a file that holds some mutant's
    # REPLACEMENT where its original should be, and refuse to start.
    #
    # ONCE, though. A leftover mutant put its replacement in exactly one place,
    # because that is what `str.replace` on a once-only anchor does. Merely
    # CONTAINING it proves nothing when the replacement is something like "}",
    # and that false positive is worse than the thing being guarded against: a
    # `pipeline.js` that had simply gone back to an older revision - anchor
    # gone, `}` present a few hundred times - read as a leftover mutant and
    # stopped every measurement in the project until someone read the tool.
    def _left_behind(f, fi, rp):
        src = (PKG / f).read_text(encoding="utf-8")
        return fi not in src and src.count(rp) == 1

    stale = [(n, f) for n, f, fi, rp, _t in MUTANTS
             if rp and (PKG / f).exists() and _left_behind(f, fi, rp)]
    if stale:
        print("REFUSING TO RUN — a previous run left a mutant on disk:")
        for n, f in stale:
            print(f"  {n}\n      in {f}")
        print("\nPut those back before measuring anything.")
        return 2

    survivors = []
    for name, rel, find, repl, tests in picked:
        f = PKG / rel
        # A mutant naming a file that is not there is stale, the same as one
        # whose anchor has moved - and it used to take the whole run down with
        # a traceback, so `-k` on a prefix that happened to match one of them
        # measured nothing at all.
        if not f.is_file():
            print(f"SKIP  {name}: no such file {rel}")
            continue
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
