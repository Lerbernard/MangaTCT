#!/usr/bin/env python3
"""Build the MangaTCT site.

Two outputs from one source: `index.html` beside `assets/` for hosting, and
`mangatct-site-standalone.html` with every picture and the font inlined, which
opens from a file:// URL with nothing beside it.

No icon set. Every picture on this page is a real screenshot of the editor or
a real page it produced - lee: *"d ont use teh icons you love to use so much"*.

**A picture that is not here yet leaves a labelled hole rather than a broken
image.** `slot()` looks for the file; if it is missing it draws a dashed box
naming the filename it wants and describing the shot. Drop the file into
`assets/`, run this again, and the hole becomes the picture with nothing else
to change. lee: *"leave spots for screenshot and picture ill give yu later"*.
"""
import base64
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(HERE, "assets")

MARK = open(f"{A}/mark.svg").read()
MARK_INNER = MARK.split(">", 1)[1].rsplit("</svg>", 1)[0]

# Everything the page asks for that is not in `assets/` yet, collected as the
# page is built and printed at the end - so "what still needs a screenshot" is
# an answer the build gives you rather than a list somebody keeps by hand.
WANTED = []


def mark(size):
    return (f'<svg class="mk" viewBox="0 0 64 64" width="{size}" height="{size}" '
            f'aria-hidden="true">{MARK_INNER}</svg>')


def have(name):
    return os.path.exists(os.path.join(A, name))


def slot(name, alt, want="", ratio="16 / 9"):
    """The picture, or a labelled hole the shape the picture will be.

    The hole carries the FILENAME, because that is the one thing you need to
    know to fill it, and a description of the shot, because six weeks later
    the filename is not enough.
    """
    if have(name):
        return f'<img src="assets/{name}" alt="{alt}" loading="lazy">'
    WANTED.append((name, want or alt))
    return (f'<div class="slot" style="aspect-ratio:{ratio}">'
            f'<span class="sn">{name}</span>'
            f'<span class="sw">{want or alt}</span></div>')


def shot(name, alt, cap=None, want="", ratio="16 / 9", cls=""):
    c = f"<figcaption>{cap}</figcaption>" if cap else ""
    return (f'<figure class="shot {cls}">{slot(name, alt, want, ratio)}{c}'
            f"</figure>")


# --------------------------------------------------------------- the content

# The hosted models, named, in the order the pricing calculator offers them.
# lee: *"talk bout the avialable ais in the page"*.
#
# Written out here rather than imported, because `build.py` uses nothing but
# the standard library and the site workflow depends on that staying true. A
# test in `tests/test_the_website.py` holds this list against `SHOW` in
# `tools/site_costs.py`, which IS generated from `coins.py` - so the two can
# never drift, and neither can drift from what the app charges.
AIS = [
    ("Gemini 2.5 Flash-Lite", "Google", "Cheapest",
     "The cheapest thing that does the job. Fine for reading text off a page."),
    ("Gemini 3.5 Flash-Lite", "Google", "Good default",
     "A generation newer for not much more. A good default."),
    ("Claude Haiku 4.5", "Anthropic", "Small and careful",
     "Claude's small one. Better at holding a voice than its price suggests."),
    ("Gemini 3.6 Flash", "Google", "The usual choice",
     "Fast, and it thinks before it answers. The usual choice for translating."),
    ("Claude Sonnet 5", "Anthropic", "For proofreading",
     "The one most people proofread with. Catches what the others miss."),
    ("Claude Opus 5", "Anthropic", "The best there is",
     "The best there is, and priced like it. Worth it on a page that matters."),
]

STEPS = [
    ("Translation", [
        ("1", "Find text", "Every block of writing on the page, boxed. "
         "comic-text-detector runs on your machine - no upload, no cost."),
        ("2", "Read text", "The Japanese, Korean or Chinese out of each box. "
         "Whole page in one request, or the page cut up for the small print."),
        ("3", "Translate", "Every box on the page in one go, with the "
         "synopsis, the character sheet and the glossary in front of it - so "
         "honorifics and names stay the same on page 39 as on page 1."),
        ("4", "Proofread <span class=\"opt\">optional</span>",
         "A second pass, only if you want one. It reads the page as a page: "
         "pronouns with no owner, a name one letter off the sheet, a line that "
         "does not answer the one before it. It writes a report you can read, "
         "and it changes nothing without you. Skip it and everything else "
         "works exactly the same."),
    ]),
    ("Image", [
        ("5", "Clean", "The Japanese comes off. Flat fill, tone copy, or the "
         "AI cleaner for the hard bits. Every bubble tells you which it used."),
        ("6", "Typeset", "The English goes in. Line breaks first, then size - "
         "never a hyphen, never a cut sentence, never a word split."),
    ]),
    ("Out", [
        ("7", "Export", "The finished pages. Or the cleaned plates. Or a "
         "sheet with every box numbered, for someone else to typeset."),
    ]),
]

# The three formats, and what is really true of each. Written against the code
# rather than against the ambition: `translate.MEDIA`, `ocr.LANG_ENGINE`,
# `order.reading_order`, `strip.py`. The rough edges are on the page on
# purpose - somebody who finds them out on their own chapter is somebody who
# stops trusting the parts that ARE good.
FORMATS = [
    {
        "id": "manga",
        "tab": "Manga",
        "lang": "Japanese",
        "dir": "Right to left",
        "line": "The format the rest of it was built around.",
        "img": "fmt-manga.jpg",
        "want": "A Japanese page in the editor with the numbered boxes on, "
                "showing the right-to-left order",
        "good": [
            ("Reading order runs right to left, panel by panel",
             "Boxes are ordered inside their panel first, and the cut is found "
             "by measuring the gutter - including slanted ones, which is most "
             "of an action page. Drag a row and the whole chapter renumbers."),
            ("Read locally by manga-ocr, no key and no upload",
             "It installs with the app and it is the strongest reader there is "
             "for Japanese comic typesetting. Or point Read text at a vision "
             "model instead - that works for all three formats."),
            ("Honorifics survive, or come off - your call",
             "-san, -sama, -kun, -chan, -senpai. And the chapter audit catches "
             "one welded onto a name where it should not be."),
            ("Two spellings of a name never become two people",
             "The name check folds Japanese romanisation - Glow and Glou, "
             "ou and oh and oo, l and r - so a drift on page 12 is caught "
             "against page 1."),
            ("Sound effects are set as words, not as kana",
             "However the original ink ran down the page, the English goes in "
             "as one horizontal word - the way a typesetter would draw it."),
        ],
        "rough": [
            ("Vertical Japanese in a narrow column is where the fitter works "
             "hardest",
             "It is handled - free text gets its own fit, and a block is "
             "allowed to run past its box rather than shrink below the "
             "legible minimum - but it is the case that produces the most "
             "corrections."),
        ],
    },
    {
        "id": "manhwa",
        "tab": "Manhwa",
        "lang": "Korean",
        "dir": "Left to right",
        "line": "Webtoon strips get cut into pages before anything else runs.",
        "img": "fmt-manhwa.jpg",
        "want": "A Korean webtoon chapter after the strip was re-cut - the "
                "page list down the side showing the new pages",
        "good": [
            ("A strip uploaded as tiles is re-cut into pages, on upload",
             "Six or more images of identical width and identical height is a "
             "sliced strip, and it is re-cut at the gutters into pages near "
             "2,400px. This exists for webtoons and has no manga equivalent."),
            ("Cut at a gutter, or told you where it could not be",
             "The cut goes to the gutter NEAREST the target, not the first one "
             "past it. Where there is no gutter inside 6,000px it cuts at the "
             "quietest row and reports that page as forced."),
            ("Your tiles are kept, never deleted",
             "They move into a folder beside the chapter. And nothing is re-cut "
             "on a chapter you have already started work on."),
            ("Speech levels reach the model",
             "해요체, 해체 and 합쇼체, and 오빠 / 언니 / 선배 - the register "
             "notes go into the prompt with the page, so politeness is not "
             "flattened into one English voice."),
            ("Left to right, and it is a setting",
             "Direction follows the format by default and you can override it "
             "per chapter."),
        ],
        "rough": [
            ("The local Korean reader is an extra install",
             "Korean and Chinese are read locally by easyocr, which does not "
             "come with the app: <code>pip install easyocr</code>. Or point "
             "Read text at a vision model and skip it entirely - that path "
             "needs nothing installed."),
            ("The reading prompt still carries Japanese instructions",
             "Rules about furigana and small kana are sent with a Korean page "
             "too. Harmless in practice, and honestly just not written yet."),
            ("The name and honorific audit knows Japanese suffixes only",
             "-ssi, -nim and 오빠 are handled by the translator and NOT by the "
             "check that runs afterwards, so a drift in a romanised Korean "
             "name is not caught for you."),
            ("Export is one file per page",
             "Nothing stitches the strip back into one long image. You get the "
             "pages the re-cut made."),
        ],
    },
    {
        "id": "manhua",
        "tab": "Manhua",
        "lang": "Chinese",
        "dir": "Left to right",
        "line": "Simplified out of the box; traditional through a vision model.",
        "img": "fmt-manhua.jpg",
        "want": "A Chinese page mid-chapter, ideally one with a dense "
                "caption box, in the Translation view",
        "good": [
            ("Simplified Chinese read locally, traditional through a model",
             "The local reader is set to simplified. A vision model reads "
             "either, and needs nothing installed."),
            ("Register carried by word choice, not by a suffix",
             "哥, 姐, 前辈 and the classical phrasing that marks a formal "
             "voice go into the prompt as notes about Chinese specifically."),
            ("The same strip handling as manhwa",
             "A tiled upload is re-cut into pages at the gutters, tiles kept, "
             "forced cuts reported."),
            ("Left to right, and it is a setting",
             "Same as manhwa: the format sets it, you can override it."),
        ],
        "rough": [
            ("The local Chinese reader is an extra install",
             "Same easyocr as Korean - <code>pip install easyocr</code>, or "
             "use a vision model."),
            ("The reading prompt still carries Japanese instructions",
             "Same as manhwa. It works; it is not written for hanzi."),
            ("The name audit knows Japanese suffixes only",
             "-ge and -jie are translated properly and are not checked "
             "afterwards."),
        ],
    },
]

TABS = [
    ("File", "Open a chapter, add pages, reorder them. One screen, one job.",
     "ui-pages.jpg", "The File tab with a chapter open and its pages listed"),
    ("Workspace", "The page. Boxes on the left of the split, typesetting on "
     "the right, every tool down the rail. This is where the work happens.",
     "ui-translation-real.jpg", "The workspace on a real page"),
    ("Results", "The proofread report and the chapter audit - what the second "
     "pass found, page by page, with the original beside it.",
     "ui-results-real.jpg",
     "The Results tab showing the proofread report on your own chapter"),
    ("Settings", "Fonts, box types, languages, models, cleaning. Per chapter, "
     "and remembered.", "ui-settings-fonts-real.jpg",
     "Settings ▸ Fonts &amp; typesetting"),
]

RULES = [
    ("The whole translation goes in.",
     "Never reworded to fit, never trimmed, never split across two boxes. "
     "The fitter changes the line breaks and the size, and that is all it is "
     "allowed to change."),
    ("No hyphens.",
     "It will not break a word to make it fit. A dash the author typed - "
     "S-S-S-SORRY!! - is a different thing and survives exactly as written."),
    ("Your font, and only your font.",
     "It will not quietly swap a character for one your face happens to have, "
     "and it will not hand a line to a different family. If your font is short "
     "of a glyph, the box says so."),
    ("It never overwrites good work with nothing.",
     "If a re-run cannot typeset a bubble - a bad font, an empty mask - the "
     "typesetting already on the page stays. A blank bubble is never an answer."),
    ("A box you drew is yours.",
     "Draw a text box and it is independent: no detection behind it, not in "
     "the translation list, not counted as text to translate. Uploading a new "
     "translation does not sweep it away."),
    ("Nothing is uploaded that you did not send.",
     "Finding text, cleaning and typesetting run locally. Reading and "
     "translating go to whichever model you point them at - including one on "
     "your own machine."),
]

CONTROL = [
    ("Every line, on the page",
     "The text list is the translation: one row per piece of source text, what "
     "it says and what it will say, and how sure the reader was. Open a row "
     "and both are fields - retype either. Change what kind of box it is, "
     "split it in two, or link it to the bubble it carries on into.",
     "ui-row-real.jpg", "An open text row with both languages showing"),
    ("Every block, letter by letter",
     "Font, size, rotation, curve, line gap, letter gap, caps. Text colour, "
     "outline colour, both as gradients. Shadow, outer glow, inner glow. Per "
     "block - not per page, not per chapter.",
     "ui-typesetting.jpg", "The typesetting rail with one block selected"),
    ("Every bubble, cleaned your way",
     "The page says which route cleaned each bubble - filled flat, tone "
     "copied, locally, by the AI - so you can see what it did before you trust "
     "it. Or drop in your own cleaned plate and skip the step.",
     "ui-clean-real.jpg", "The cleaning panel showing the route per bubble"),
]

COMPARE = [
    ("Detection, reading and translation", "by hand, box by box",
     "one pass, whole chapter", "one pass, whole chapter"),
    ("Where the English goes", "you place every block",
     "you place every block", "fitted, then you correct it"),
    ("Change one bubble's font", "yes", "yes", "yes"),
    ("Gradients, glow, curve, rotation per block", "yes", "yes", "yes"),
    ("Draw, clone, heal and erase on the page", "yes", "yes", "yes"),
    ("Reading order enforced across the chapter", "you track it",
     "you track it", "numbered, and re-numbered when you drag"),
    ("Glossary and character sheet applied to every page", "you remember",
     "you remember", "carried into every request"),
    ("Runs the model you choose, or none at all", "no model",
     "fixed", "per step, including local"),
    ("Translate it entirely by hand", "yes", "no",
     "yes - a labelled file out, filled in, back"),
    ("Webtoon strips cut into pages", "you cut them", "rarely",
     "on upload, at the gutters"),
    ("Your own cleaned pages", "they are yours", "rarely", "drop them in"),
]

FAQ = [
    ("What do I need to run it?",
     "A machine with Python. The text detector is a single model file you "
     "download once and it runs on the processor - no graphics card needed. "
     "Reading and translating need an API key for whichever model you pick, "
     "or a local one; cleaning can run entirely offline."),
    ("Does it upload my raws?",
     "Finding text, cleaning, typesetting and exporting never leave your "
     "machine. Reading and translating send the page - or just the text - to "
     "the model you chose. Point them at something running on your own "
     "computer and nothing leaves at all."),
    ("What about long webtoon strips?",
     "A chapter uploaded as identical tiles is re-cut into pages near 2,400px "
     "on upload, at the gutters, and your tiles are kept. It is done because "
     "the detector sees a whole page at one size, so on a 10,000px strip the "
     "text arrives too small to find. A single genuinely enormous image that "
     "was never tiled is still the weak spot - cut it up first."),
    ("Which languages can it translate into?",
     "English, Spanish, Portuguese and French. The prompt is warned that "
     "Spanish and Portuguese run about a fifth longer than English and French "
     "about a quarter, because that is the difference between a balloon that "
     "fits and one that does not."),
    ("Can I use it without any AI?",
     "Yes. Turn on manual translation and the three model steps go quiet. "
     "Download a labelled text file with every box numbered, fill it in, "
     "upload it back - or type straight into the page."),
    ("Is it finished?",
     "No. It typesets a chapter today and it is being worked on most days. "
     "The parts that have settled - finding text, reading it, translating, "
     "cleaning - are the parts that get left alone."),
]


# ------------------------------------------------------------------ the page

def build():
    groups = "".join(
        f'<div class="grp"><p class="gname">{name}</p><div class="gsteps">'
        + "".join(
            f'<article class="step" data-step="{n}"><b>{n}</b>'
            f"<h4>{t}</h4><p>{d}</p></article>" for n, t, d in items)
        + "</div></div>"
        for name, items in STEPS)

    fmt_tabs = "".join(
        f'<button class="tb" role="tab" aria-selected="{str(i == 0).lower()}" '
        f'aria-controls="f-{f["id"]}" id="t-{f["id"]}">{f["tab"]}'
        f'<span>{f["lang"]}</span></button>'
        for i, f in enumerate(FORMATS))

    # Left: what the format is, then what works. Right: the picture, then the
    # honest list. Stacking them this way keeps the two columns near the same
    # height whichever tab is open - the rough list is always the shorter one,
    # and a picture above it is what makes that look deliberate.
    fmt_panels = "".join(
        f'<section class="pan" role="tabpanel" id="f-{f["id"]}" '
        f'aria-labelledby="t-{f["id"]}"{"" if i == 0 else " hidden"}>'
        f'<div class="two pantop">'
        f'<div><h3>{f["tab"]} <span class="mut">| {f["lang"]}</span></h3>'
        f'<p class="panlead">{f["line"]}</p>'
        f'<p class="chips"><span class="chip">{f["lang"]}</span>'
        f'<span class="chip">{f["dir"]}</span></p>'
        f'<p class="sub good">What it does well</p><dl>'
        + "".join(f"<dt>{t}</dt><dd>{d}</dd>" for t, d in f["good"])
        + "</dl></div>"
        f'<div><figure class="shot pan-img" style="margin-bottom:26px">'
        f'{slot(f["img"], f["tab"] + " in the editor", f["want"], "16 / 10")}'
        f"</figure>"
        f'<div class="roughbox"><p class="sub rough">Where it is rough</p><dl>'
        + "".join(f"<dt>{t}</dt><dd>{d}</dd>" for t, d in f["rough"])
        + "</dl></div></div></div></section>"
        for i, f in enumerate(FORMATS))

    screens = "".join(
        f'<button class="tb" role="tab" aria-selected="{str(i == 0).lower()}" '
        f'aria-controls="s-{i}" id="st-{i}">{t}</button>'
        for i, (t, d, img, want) in enumerate(TABS))
    screen_panels = "".join(
        f'<section class="pan" role="tabpanel" id="s-{i}" '
        f'aria-labelledby="st-{i}"{"" if i == 0 else " hidden"}>'
        f'<div class="two tight"><div><h3>{t}</h3><p class="mut">{d}</p></div>'
        f'<figure class="shot">{slot(img, t + " tab", want)}</figure></div>'
        "</section>"
        for i, (t, d, img, want) in enumerate(TABS))

    ais = "".join(
        f'<article class="ai"><span class="who">{who}</span>'
        f'<h4>{name}</h4><span class="for">{tag}</span><p>{why}</p></article>'
        for name, who, tag, why in AIS)

    rules = "".join(f'<article class="rule"><h4>{t}</h4><p>{d}</p></article>'
                    for t, d in RULES)
    control = "".join(
        f'<div class="ctl rise"><div class="ctltx"><h3>{t}</h3><p>{d}</p></div>'
        f'<figure class="shot">{slot(img, t, want, "4 / 3")}</figure></div>'
        for t, d, img, want in CONTROL)
    rows = "".join(
        f"<tr><th>{a}</th><td>{b}</td><td>{c}</td><td class=\"me\">{d}</td></tr>"
        for a, b, c, d in COMPARE)
    faq = "".join(f"<details><summary>{q}</summary><p>{a}</p></details>"
                  for q, a in FAQ)

    # The before/after handle. Both halves have to exist for it to mean
    # anything, so when either is missing the whole thing becomes one labelled
    # hole rather than a slider with a hole on one side of it.
    if have("ba-before.jpg") and have("ba-after.jpg"):
        ba = ('<div class="ba" id="ba">'
              '<img class="ba-a" src="assets/ba-before.jpg" alt="The raw page">'
              '<div class="ba-b"><img src="assets/ba-after.jpg" '
              'alt="The same page, cleaned and typeset in English"></div>'
              '<div class="ba-h" aria-hidden="true"><i></i></div>'
              '<input type="range" min="0" max="100" value="52" step="0.1" '
              'aria-label="Reveal the typeset page"></div>')
    else:
        WANTED.append(("ba-before.jpg / ba-after.jpg",
                       "ONE page, twice: the raw scan and the finished export, "
                       "same size, same crop. This is the most important "
                       "picture on the site."))
        ba = ('<div class="slot tall" style="aspect-ratio:3 / 2">'
              '<span class="sn">ba-before.jpg + ba-after.jpg</span>'
              '<span class="sw">One page, twice - the raw scan and the '
              'finished export, same size and same crop. Drop both in and '
              'this becomes a slider you drag.</span></div>')

    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MangaTCT - translate, clean, typeset</title>
<meta name="description" content="A manga, manhwa and manhua translation
 editor. Finds the text, reads it, translates it, cleans the page and typesets
 it - and hands you every one of those decisions.">
<link rel="icon" href="assets/mark.svg" type="image/svg+xml">
<!-- Read and applied before the stylesheet paints. It has to be here and
     inline: a theme applied after first paint is a white flash on a dark page,
     every single load. -->
<script>try{{var t=localStorage.getItem('tct-theme');if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
<style>
@font-face{{font-family:AntonLocal;src:url(assets/anton.ttf) format('truetype');
 font-display:swap}}

/* ---------------------------------------------------------------- tokens */
:root{{
 --bg:#0b0d12; --bg2:#0f131a; --panel:#141922; --panel2:#1a2029;
 --line:#232b38; --line2:#2f3947;
 --fg:#eef1f6; --dim:#98a2b5; --dim2:#6f7a8d;
 --accent:#ffc400; --accent2:#ff9d00; --ok:#7fd39b; --warn:#ffb35c;
 --on-accent:#141821; --hair:rgba(255,255,255,.03);
 --shadow:0 34px 90px rgba(0,0,0,.6); --glow:rgba(255,196,0,.13);
 --r:14px; --rs:10px;
 --w:1180px;
 --sec:clamp(56px,7vw,88px);
}}

/* Light, for a system that asked for it. The media query is the DEFAULT and
   the attribute is the DECISION, in that order: a browser that has never
   pressed the control in the header follows the operating system for ever,
   and one that has pressed it keeps what it chose until it is pressed back
   round to Auto. */
@media(prefers-color-scheme:light){{
 :root{{
  --bg:#f4f6fa; --bg2:#eceff5; --panel:#ffffff; --panel2:#f1f4f9;
  --line:#dde3ec; --line2:#c3ccdb;
  --fg:#151a22; --dim:#5c6779; --dim2:#7b8698;
  --accent:#ffb300; --accent2:#ff8f00; --ok:#1f7a44; --warn:#a35b00;
  --on-accent:#241a04; --hair:rgba(0,0,0,.02);
  --shadow:0 24px 60px rgba(15,23,42,.14); --glow:rgba(255,179,0,.18);
 }}
}}
html[data-theme="dark"]{{
 --bg:#0b0d12; --bg2:#0f131a; --panel:#141922; --panel2:#1a2029;
 --line:#232b38; --line2:#2f3947;
 --fg:#eef1f6; --dim:#98a2b5; --dim2:#6f7a8d;
 --accent:#ffc400; --accent2:#ff9d00; --ok:#7fd39b; --warn:#ffb35c;
 --on-accent:#141821; --hair:rgba(255,255,255,.03);
 --shadow:0 34px 90px rgba(0,0,0,.6); --glow:rgba(255,196,0,.13);
}}
html[data-theme="light"]{{
 --bg:#f4f6fa; --bg2:#eceff5; --panel:#ffffff; --panel2:#f1f4f9;
 --line:#dde3ec; --line2:#c3ccdb;
 --fg:#151a22; --dim:#5c6779; --dim2:#7b8698;
 --accent:#ffb300; --accent2:#ff8f00; --ok:#1f7a44; --warn:#a35b00;
 --on-accent:#241a04; --hair:rgba(0,0,0,.02);
 --shadow:0 24px 60px rgba(15,23,42,.14); --glow:rgba(255,179,0,.18);
}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
body{{margin:0;background:var(--bg);color:var(--fg);
 font:16px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
 -webkit-font-smoothing:antialiased}}
img{{max-width:100%;display:block}}
/* No underlines anywhere. lee: *"avoid having underlines in links"*. A link
   earns its difference from the colour and from moving when you point at it,
   not from a line drawn through the descenders. */
a{{color:var(--accent);text-decoration:none}}
a:hover{{text-decoration:none}}
:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
code{{font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;
 background:var(--panel2);border:1px solid var(--line);border-radius:5px;
 padding:1px 5px;color:var(--fg)}}
.wrap{{max-width:var(--w);margin:0 auto;padding:0 24px}}
h1,h2,h3,h4,.brand b,.brand i,.step b,.stat b{{
 font-family:AntonLocal,Impact,"Arial Narrow Bold",sans-serif;
 font-weight:400;letter-spacing:.005em;line-height:1.05}}
h2{{font-size:clamp(29px,4.1vw,44px);margin:0 0 12px}}
h3{{font-size:21px;margin:0 0 7px}}
h4{{font-size:18px;margin:0 0 5px}}
p{{margin:0 0 14px}}
.lead{{color:var(--dim);font-size:18px;max-width:64ch}}
.mut{{color:var(--dim)}}
/* Each section is its own SURFACE, not another stretch of the same column.
   lee: *"make each section fell like their own thing so it dont feel like an
   endless page of text"*. Alternating grounds and a hairline at the top of
   each one give the eye somewhere to stop, and the accent rule says which
   thing you are now in. */
section.band{{padding:var(--sec) 0;position:relative}}
section.band+section.band{{border-top:1px solid var(--line)}}
section.band:nth-of-type(odd){{background:var(--bg2)}}
section.band>.wrap{{position:relative}}
section.band>.wrap:before{{content:"";position:absolute;left:24px;top:-6px;
 width:54px;height:3px;border-radius:2px;
 background:linear-gradient(90deg,var(--accent),transparent)}}
.hero+.band{{border-top:1px solid var(--line)}}
/* Every anchored section has to clear the sticky header, or following a nav
   link lands with the heading tucked underneath it. */
[id]{{scroll-margin-top:84px}}
.kicker{{font-size:11.5px;letter-spacing:.22em;text-transform:uppercase;
 color:var(--accent);margin:0 0 12px;font-weight:700}}

/* ------------------------------------------------------ appear on scroll */
.rise{{opacity:0;transform:translateY(16px);
 transition:opacity .5s ease,transform .5s ease}}
.rise.in{{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){{
 .rise{{opacity:1;transform:none;transition:none}}
}}
/* Nothing may be hidden for a reader with JS off - the observer never runs,
   so the starting state has to be the visible one for them. */
.nojs .rise{{opacity:1;transform:none}}

/* ---------------------------------------------------------------- header */
header{{position:sticky;top:0;z-index:60;background:var(--bg);
 backdrop-filter:blur(12px) saturate(1.3);border-bottom:1px solid var(--line)}}
.hd{{display:flex;align-items:center;gap:26px;height:64px}}
.brand{{display:flex;align-items:flex-end;gap:9px;text-decoration:none;color:inherit}}
.brand svg{{display:block}}
/* MangaTCT is one word. `gap` on a flex row falls between EVERY child, so the
   space meant to sit between the mark and the name was also splitting the
   name in half. */
.brand .wm{{display:flex;align-items:flex-end;gap:0}}
.brand b{{font-size:25px;line-height:.82}}
.brand i{{font-size:25px;line-height:.82;color:var(--accent);font-style:normal}}
.hd nav{{margin-left:auto;display:flex;gap:8px;font-size:14px;
 align-items:center;flex-wrap:wrap}}
/* Pills, not a row of words. Six links in a line all the same colour read as
   one sentence you cannot press. */
.hd nav a,.navb{{color:var(--dim);text-decoration:none;padding:7px 13px;
 border:1px solid var(--line);border-radius:999px;line-height:1;
 white-space:nowrap;background:transparent;font:inherit;font-size:14px;
 font-weight:600;cursor:pointer;display:inline-flex;align-items:center;
 gap:7px;transition:color .15s ease,border-color .15s ease,
 background .15s ease,transform .15s ease}}
.hd nav a:hover,.navb:hover{{color:var(--fg);border-color:var(--line2);
 background:var(--panel2);transform:translateY(-1px)}}
.navb.icon{{padding:7px;width:34px;height:34px;justify-content:center;
 color:var(--dim)}}
.navb svg{{display:block}}
.btn{{display:inline-block;background:var(--accent);color:var(--on-accent);
 padding:11px 20px;border-radius:9px;font-weight:700;text-decoration:none;
 font-size:15px;border:1px solid var(--accent);transition:transform .12s ease,
 background .12s ease}}
.btn:hover{{filter:brightness(1.07);transform:translateY(-1px)}}
.btn.ghost{{background:transparent;color:var(--fg);border-color:var(--line2)}}
.btn.ghost:hover{{background:var(--panel2)}}

/* ------------------------------------------------------------------ hero */
.hero{{padding:clamp(56px,7vw,92px) 0 0;position:relative;overflow:hidden}}
.hero:before{{content:"";position:absolute;inset:-30% 30% 55% -10%;
 background:radial-gradient(closest-side,var(--glow),transparent 70%);
 pointer-events:none}}
.hero .wrap{{position:relative}}
.hero h1{{font-size:clamp(38px,5.2vw,66px);margin:0 0 18px;max-width:24ch}}
.hero h1 em{{font-style:normal;
 background:linear-gradient(96deg,var(--accent),var(--accent2));
 -webkit-background-clip:text;background-clip:text;color:transparent}}
.hero .lead{{font-size:19.5px;max-width:60ch}}
.cta{{display:flex;gap:12px;flex-wrap:wrap;margin:28px 0 10px;align-items:center}}
.note{{color:var(--dim2);font-size:13.5px}}
.heroshot{{margin-top:44px;border:1px solid var(--line);border-radius:var(--r);
 overflow:hidden;background:var(--panel);box-shadow:var(--shadow)}}
.stats{{display:flex;gap:40px;flex-wrap:wrap;margin:26px 0 0}}
.stat b{{display:block;font-size:30px;color:var(--fg);line-height:1}}
.stat span{{color:var(--dim);font-size:14px}}

/* ------------------------------------------------------------ the models */
.ais{{display:grid;gap:14px;margin-top:22px;
 grid-template-columns:repeat(auto-fit,minmax(238px,1fr))}}
.ai{{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
 padding:17px 18px;position:relative;overflow:hidden;
 transition:transform .16s ease,border-color .16s ease}}
.ai:hover{{transform:translateY(-3px);border-color:var(--line2)}}
.ai:before{{content:"";position:absolute;inset:0 0 auto 0;height:2px;
 background:linear-gradient(90deg,var(--accent),transparent 70%)}}
.ai .who{{font-size:11px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--dim2);font-weight:700}}
.ai h4{{margin:6px 0 6px}}
.ai .for{{display:inline-block;font-size:11.5px;font-weight:700;
 color:var(--accent);border:1px solid var(--line2);border-radius:999px;
 padding:2px 9px;margin-bottom:9px}}
.ai p{{margin:0;color:var(--dim);font-size:14px}}

/* A step that is a choice says so in the heading, not in a footnote. */
.opt{{font-family:inherit;font-size:11px;letter-spacing:.1em;
 text-transform:uppercase;font-weight:700;color:var(--accent);
 border:1px solid var(--line2);border-radius:999px;padding:2px 8px;
 margin-left:8px;vertical-align:middle;white-space:nowrap}}

/* -------------------------------------------------------- picture holes */
.slot{{width:100%;border:1.5px dashed var(--line2);border-radius:var(--r);
 background:repeating-linear-gradient(135deg,var(--panel) 0 12px,
  var(--bg2) 12px 24px);
 display:flex;flex-direction:column;align-items:center;justify-content:center;
 gap:8px;text-align:center;padding:26px;color:var(--dim2)}}
.slot .sn{{font:12px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;
 color:var(--accent);letter-spacing:.02em}}
.slot .sw{{font-size:13.5px;max-width:46ch;color:var(--dim)}}

/* ----------------------------------------------------------- before/after */
.ba{{position:relative;border:1px solid var(--line);border-radius:var(--r);
 overflow:hidden;background:var(--panel);touch-action:none;
 box-shadow:0 30px 80px rgba(0,0,0,.5)}}
.ba img{{width:100%;display:block}}
.ba-b{{position:absolute;inset:0;width:var(--x,52%);overflow:hidden}}
.ba-b img{{position:absolute;top:0;left:0;height:100%;width:auto;
 max-width:none}}
.ba-h{{position:absolute;top:0;bottom:0;left:var(--x,52%);width:2px;
 background:var(--accent);transform:translateX(-1px);pointer-events:none}}
.ba-h i{{position:absolute;top:50%;left:50%;width:44px;height:44px;
 margin:-22px 0 0 -22px;border-radius:50%;background:var(--accent);
 box-shadow:0 4px 18px rgba(0,0,0,.5)}}
.ba input[type=range]{{position:absolute;inset:0;width:100%;height:100%;
 opacity:0;cursor:ew-resize;margin:0}}
.balabels{{display:flex;justify-content:space-between;color:var(--dim2);
 font-size:12.5px;letter-spacing:.14em;text-transform:uppercase;margin-top:10px}}

/* -------------------------------------------------------------- the walk */
.walk{{display:grid;grid-template-columns:230px 1fr;gap:46px;align-items:start}}
/* A grid track's default `min-width:auto` is as wide as its widest child, so
   the scrolling rail below was making the whole page scroll sideways instead
   of scrolling itself. */
.walk>*{{min-width:0}}
.walk .rail{{position:sticky;top:96px}}
.walk .rail ol{{list-style:none;margin:0;padding:0}}
.walk .rail li{{display:flex;gap:11px;align-items:baseline;padding:7px 0;
 color:var(--dim2);font-size:14.5px;border-left:2px solid var(--line);
 padding-left:14px;transition:color .2s ease,border-color .2s ease}}
.walk .rail li.on{{color:var(--fg);border-left-color:var(--accent)}}
.walk .rail li em{{font-style:normal;color:var(--dim2);font-size:12px;
 min-width:12px}}
.walk .rail li.on em{{color:var(--accent)}}
.grp{{margin-bottom:34px}}
.gname{{font-size:11.5px;letter-spacing:.22em;text-transform:uppercase;
 color:var(--dim2);margin:0 0 12px;font-weight:700}}
.gsteps{{display:grid;gap:14px;grid-template-columns:repeat(2,1fr)}}
.step{{background:var(--panel);border:1px solid var(--line);
 border-radius:var(--r);padding:18px 20px;position:relative;
 transition:border-color .2s ease,transform .2s ease}}
.step:hover{{border-color:var(--line2);transform:translateY(-2px)}}
.step b{{position:absolute;top:13px;right:16px;font-size:32px;color:#1e2531}}
.step p{{color:var(--dim);font-size:14.5px;margin:0}}

/* --------------------------------------------------------------- tabs */
.tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 26px}}
.tb{{appearance:none;background:var(--panel);color:var(--dim);
 border:1px solid var(--line);border-radius:999px;padding:9px 18px;
 font:inherit;font-size:15px;font-weight:600;cursor:pointer;
 display:flex;align-items:baseline;gap:8px;
 transition:color .15s ease,border-color .15s ease,background .15s ease}}
.tb span{{font-size:12px;font-weight:400;color:var(--dim2)}}
.tb:hover{{color:var(--fg);border-color:var(--line2)}}
.tb[aria-selected=true]{{color:#141821;background:var(--accent);
 border-color:var(--accent)}}
.tb[aria-selected=true] span{{color:#4a3d00}}
.pan[hidden]{{display:none}}
.pan-img img{{max-height:330px;object-fit:cover;object-position:top}}
.pantop{{align-items:start}}
.pantop .chips{{margin-bottom:34px}}
.pantop .sub{{margin-top:0}}
.panlead{{color:var(--dim);font-size:17px;margin:0 0 12px}}
.chips{{display:flex;gap:8px;flex-wrap:wrap;margin:0}}
.chip{{border:1px solid var(--line2);border-radius:999px;padding:4px 12px;
 font-size:12.5px;color:var(--dim)}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:36px}}
.two.tight{{grid-template-columns:1fr 1.15fr;align-items:center}}
.sub{{font-size:11.5px;letter-spacing:.2em;text-transform:uppercase;
 font-weight:700;margin:0 0 16px}}
.sub.good{{color:var(--ok)}}
.sub.rough{{color:var(--warn)}}
/* The rough column is usually shorter than the good one, and a short bare
   column reads as a mistake. Boxing it makes the asymmetry look like what it
   is - a deliberately shorter list - and it is the part worth reading twice. */
.roughbox{{background:var(--panel);border:1px solid var(--line);
 border-left:3px solid var(--warn);border-radius:var(--r);padding:22px 24px 6px;
 align-self:start}}
.roughbox dd:last-of-type{{margin-bottom:16px}}
dl{{margin:0}}
dt{{font-weight:650;margin:0 0 4px}}
dd{{margin:0 0 18px;color:var(--dim);font-size:14.5px}}

/* -------------------------------------------------------------- blocks */
.grid{{display:grid;gap:18px}}
.g3{{grid-template-columns:repeat(3,1fr)}}
.g2{{grid-template-columns:repeat(2,1fr)}}
.card{{background:var(--panel);border:1px solid var(--line);
 border-radius:var(--r);padding:20px}}
.rule{{background:var(--panel);border:1px solid var(--line);
 border-radius:var(--r);padding:18px 20px}}
.rule h4{{color:var(--accent)}}
.rule p{{color:var(--dim);font-size:14.5px;margin:0}}
figure.shot{{margin:0}}
figure.shot img{{border:1px solid var(--line);border-radius:var(--r);
 background:var(--panel)}}
figcaption{{color:var(--dim);font-size:13px;margin-top:9px;max-width:70ch}}
.ctl{{display:grid;grid-template-columns:1fr 400px;gap:36px;align-items:center;
 padding:30px 0;border-top:1px solid var(--line)}}
.ctl:first-child{{border-top:0;padding-top:0}}
.ctl p{{color:var(--dim);margin:0}}
.clips{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}
.clip{{background:var(--panel);border:1px solid var(--line);
 border-radius:var(--r);padding:14px}}
.clip img,.clip .slot{{border-radius:var(--rs);width:100%}}
.clip h4{{margin:12px 0 4px;font-size:17px}}
.clip p{{color:var(--dim);font-size:14px;margin:0}}

/* -------------------------------------------------------------- table */
.tblwrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:14.5px;min-width:640px}}
th,td{{text-align:left;padding:13px 14px;border-top:1px solid var(--line);
 vertical-align:top}}
thead th{{color:var(--dim);font-size:11.5px;letter-spacing:.16em;
 text-transform:uppercase;border-top:0;font-weight:700;font-family:inherit}}
tbody th{{font-weight:650;color:var(--fg);width:32%;font-family:inherit}}
td{{color:var(--dim)}}
td.me{{color:var(--fg)}}
thead th.me{{color:var(--accent)}}
tbody tr:hover td,tbody tr:hover th{{background:var(--bg2)}}

details{{border-top:1px solid var(--line);padding:16px 0}}
summary{{cursor:pointer;font-weight:650;font-size:17px;list-style:none}}
summary::-webkit-details-marker{{display:none}}
summary:before{{content:"+";color:var(--accent);margin-right:11px;
 font-weight:700;display:inline-block;width:12px}}
details[open] summary:before{{content:"\\2013"}}
details p{{color:var(--dim);margin:10px 0 0 23px;max-width:78ch}}

footer{{border-top:1px solid var(--line);padding:44px 0 64px;color:var(--dim);
 font-size:14px;background:var(--bg2)}}
.foot{{display:flex;gap:22px;flex-wrap:wrap;align-items:center}}
.foot .brand b,.foot .brand i{{font-size:20px}}
.built{{margin-left:auto;color:var(--dim2)}}
.built b{{color:var(--fg);font-weight:650}}
.todo{{background:#241f08;border:1px dashed #6b5a12;color:#e8d48a;
 padding:2px 7px;border-radius:5px;font-size:12px}}

@media(max-width:980px){{
 .walk{{grid-template-columns:1fr;gap:24px}}
 .walk .rail{{position:static}}
 .walk .rail ol{{display:flex;gap:8px;overflow-x:auto;padding-bottom:6px}}
 .walk .rail li{{border-left:0;border-bottom:2px solid var(--line);
  padding:6px 10px 8px;white-space:nowrap}}
 .walk .rail li.on{{border-bottom-color:var(--accent)}}
 .pantop,.two,.two.tight,.ctl,.g3,.g2,.clips,.gsteps{{grid-template-columns:1fr}}
 .ais{{grid-template-columns:1fr}}
 /* The in-page anchors go; Pricing and the theme control stay. Hiding the
    whole nav took the theme button with it, which is the one thing on this
    bar a phone is MORE likely to want than a desktop. */
 .hd nav a[href^="#"]{{display:none}}
 .hd nav{{gap:6px}}
}}
@media(max-width:560px){{
 .hd{{height:auto;padding:10px 0;flex-wrap:wrap;gap:10px}}
 .stats{{gap:22px}}
 .cta .btn{{width:100%}}
}}
</style>

<header><div class="wrap hd">
  <a class="brand" href="#top">{mark(28)}<span class="wm"><b>Manga</b><i>TCT</i></span></a>
  <nav>
    <a href="#how">How it works</a>
    <a href="#formats">Manga | manhwa | manhua</a>
    <a href="#control">Control</a>
    <a href="#compare">Compare</a>
    <a href="#credits">Coins</a>
    <a href="pricing.html">Pricing</a>
    <button class="navb icon" id="theme" type="button"></button>
  </nav>
  <a class="btn" href="signin.html">Sign in</a>
</div></header>

<a id="top"></a>

<section class="hero"><div class="wrap">
  <p class="kicker">Manga | manhwa | manhua</p>
  <h1>Translate, clean and typeset a chapter <em>without giving up the page</em></h1>
  <p class="lead">MangaTCT finds every block of text, reads it, translates it
  with your glossary and your character sheet, wipes the original off the art
  and sets the English back into the balloon. Then it hands you all of it:
  every line, every block, every bubble, down to the outline colour.</p>
  <div class="cta">
    <a class="btn" href="#credits">Start free - you get credits to try it</a>
    <a class="btn ghost" href="#how">See it work</a>
  </div>
  <p class="note">Free credits on signup, no card. Finding text, cleaning and
  typesetting run on your own machine and cost nothing.</p>
  <div class="heroshot">{slot('ui-hero-real.jpg',
    'The MangaTCT workspace: a chapter typeset in English, with the seven '
    'steps across the top and the cleaning panel on the right',
    'The workspace on a finished chapter, the whole window', '16 / 10')}</div>
  <div class="stats">
    <span class="stat"><b>3</b><span>formats, end to end</span></span>
    <span class="stat"><b>7</b><span>steps, run in any order</span></span>
    <span class="stat"><b>4</b><span>languages out</span></span>
    <span class="stat"><b>0</b><span>hyphens, ever</span></span>
  </div>
</div></section>

<section class="band" id="how"><div class="wrap">
  <p class="kicker">Drag it</p>
  <h2 class="rise">A raw page in. A typeset page out.</h2>
  <p class="lead rise">One file, both ends of the pipeline. Pull the handle
  across.</p>
  <div class="rise" style="margin:30px 0 0">{ba}</div>
  <div class="balabels"><span>Raw</span><span>Typeset</span></div>
  <div class="clips rise" style="margin-top:36px">
    <div class="clip">{slot('clip-pipeline.gif',
      'The three stages cycling: raw, cleaned, typeset',
      'A short loop of one page going raw to cleaned to typeset')}
      <h4>The three stages</h4>
      <p>Find and read, clean, typeset. Each stage is a step you can run, undo
      and run again on one page or the whole chapter.</p></div>
    <div class="clip">{slot('clip-fit.gif',
      'One balloon typeset with four different lengths of English',
      'A loop of one balloon fitted with four lengths of English')}
      <h4>The fitter, working</h4>
      <p>Same balloon, four lengths of English. It changes the breaks and the
      size - 34pt down to 16pt - and never the words.</p></div>
    <div class="clip">{slot('clip-font.gif',
      'The same balloon typeset in four different fonts',
      'A loop of one balloon in four different faces')}
      <h4>One block, four faces</h4>
      <p>A font is a decision about a block, not about a chapter. Change it on
      one bubble and nothing else moves.</p></div>
  </div>
</div></section>

<section class="band"><div class="wrap">
  <p class="kicker">The pipeline</p>
  <h2 class="rise">Seven steps, in three groups.</h2>
  <p class="lead rise" style="margin-bottom:38px">The bar says where the chapter
  is - a count on every button and a fill under it. It does not decide what you
  are allowed to press: run any step, in any order, on any pages you like.</p>
  <div class="walk">
    <div class="rail"><ol id="rail">
      {"".join(f'<li data-for="{n}"><em>{n}</em>{t}</li>'
               for _g, items in STEPS for n, t, _d in items)}
    </ol></div>
    <div>{groups}</div>
  </div>
  <div class="rise" style="margin-top:40px">{shot('ui-steps-real.jpg',
    'The seven-step bar on a finished chapter',
    'A real chapter, six steps done, twenty-three pages each.',
    'The step bar with every step reading 23 of 23', '21 / 4')}</div>
</div></section>

<section class="band" id="formats"><div class="wrap">
  <p class="kicker">Three formats</p>
  <h2 class="rise">Manga, manhwa and manhua - what changes between them.</h2>
  <p class="lead rise" style="margin-bottom:30px">All three are supported end
  to end. They are not the same job, though, and a tool that pretends they are
  is a tool that hands you a Korean chapter numbered backwards. Here is what
  actually differs - including the parts that are still rough.</p>
  <div class="tabs rise" role="tablist" id="fmttabs">{fmt_tabs}</div>
  <div class="rise" id="fmtpanels">{fmt_panels}</div>
  <p class="note" style="margin-top:30px">Everything AFTER the words is the
  same for all three: cleaning, fitting, typesetting, the effects and the
  export do not know which format they are working on, and that is deliberate.
  Out comes English, Spanish, Portuguese or French.</p>
</div></section>

<section class="band"><div class="wrap">
  <p class="kicker">The screens</p>
  <h2 class="rise">Four tabs, and only one of them is ever in your way.</h2>
  <div class="tabs rise" role="tablist" id="scrtabs" style="margin-top:24px">{screens}</div>
  <div class="rise">{screen_panels}</div>
</div></section>

<section class="band" id="control"><div class="wrap">
  <p class="kicker">Editorial control</p>
  <h2 class="rise">The machine does the typing. You do the editing.</h2>
  <p class="lead rise">This is the part most tools skip. Everything the pipeline
  decided is a value you can see and change, on the page, without leaving the
  editor and without starting again.</p>
  <div style="margin-top:30px">{control}</div>
  <div class="rise" style="margin-top:38px">{shot('ui-typesetting-full.jpg',
    'The whole workspace with one block selected and the typesetting panel open',
    'One block picked, and every control that applies to it.',
    'The workspace with a block selected and the typesetting rail open')}</div>
</div></section>

<section class="band" id="rules"><div class="wrap">
  <p class="kicker">What it will not do</p>
  <h2 class="rise">Six rules it will not break to make your life easier.</h2>
  <p class="lead rise">A tool that quietly edits your translation to make it fit
  is not saving you work - it is hiding work you now have to find.</p>
  <div class="grid g3 rise" style="margin-top:28px">{rules}</div>
  <div class="grid g2 rise" style="margin-top:30px">
    {shot('cmp-substitutes.jpg',
      'The same page typeset twice, with glyph substitution off and on',
      'Your font, and only your font. Left: the switch off - the character '
      'your face cannot draw is KEPT and the box is flagged by name. Right: '
      'the switch on, if you want it.',
      'One page typeset twice: substitution off, then on', '4 / 3')}
    {shot('cmp-spill.jpg',
      'A sound effect typeset inside its box, and again spilling out of it',
      'Outside text and sound effects sit on artwork, not on paper. Rather '
      'than shrink under the legible minimum they are set at it and allowed '
      'to run past the box - the way a typesetter would.',
      'The same effect at the minimum size, boxed and spilling', '4 / 3')}
  </div>
</div></section>

<section class="band"><div class="wrap">
  <p class="kicker">The models</p>
  <h2 class="rise">Bring your own AI. Or none.</h2>
  <div class="two tight rise" style="margin-top:28px">
    <div>
      <p>Reading, translating and proofreading each take their own service and
      their own model, so you can put a cheap fast one on the reading and a
      careful one on the words. <b>Claude, Google AI Studio or OpenRouter</b> -
      one key per service, not one per step - or a model running on your own
      machine.</p>
      <p>The menu only ever offers models this app can PRICE and your key can
      actually REACH, crossed together. A model you cannot run never appears in
      it, and neither does one nobody has priced. Nothing a generation behind
      is offered at all.</p>
      <p><b>Or do it entirely by hand.</b> Turn on manual translation and the
      three model steps go quiet. You get a labelled text file with every box
      numbered the way the box sheet numbers it, the original beside each one
      and room to type underneath. Fill in as much as you like, upload it back,
      and whatever is in it wins.</p>
    </div>
    <figure class="shot">{slot('ui-settings-models-real.jpg',
      'Per-step model settings',
      'Settings ▸ the model for each step, with the three services and the '
      'API keys block', '4 / 3')}</figure>
  </div>
  <h3 class="rise" style="margin-top:44px">What you can point them at</h3>
  <p class="lead rise">Six, from about a penny a chapter to about four dollars.
  Every one of them is priced per text box on what it really costs to run, and
  the calculator on the coins page will tell you the number before you spend
  anything.</p>
  <div class="ais rise">{ais}</div>
  <p class="note">Or your own key, or a model on your own machine, in which
  case none of this costs anything here.</p>

  <div class="rise" style="margin-top:38px">{shot('ui-settings-fonts-real.jpg',
    'Settings: fonts and typesetting, with a face per box type',
    'Fonts you upload stay with YOU, not with the chapter - the next project '
    'already has them. Every box type gets its own face, and you can add your '
    'own types: caption box, thought bubble, burst, whisper, aside, sign.',
    'Settings ▸ Fonts and typesetting')}</div>
</div></section>

<section class="band" id="compare"><div class="wrap">
  <p class="kicker">Compared</p>
  <h2 class="rise">Against the two ways people do this now.</h2>
  <p class="lead rise">Doing it by hand gives you total control and costs you a
  day a chapter. A one-click translator gives you a chapter in a minute and no
  way to fix what it got wrong. This sits in the middle on purpose.</p>
  <div class="tblwrap rise" style="margin-top:28px"><table>
    <thead><tr><th></th><th>By hand in Photoshop</th>
      <th>One-click auto-translate</th><th class="me">MangaTCT</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <p class="note" style="margin-top:14px">The middle column describes the
  general class of one-click page translators, not any single product.</p>
</div></section>

<section class="band" id="credits"><div class="wrap">
  <p class="kicker">Credits</p>
  <h2 class="rise">Free to try. Then you pay for what you actually run.</h2>
  <p class="lead rise">Make an account and it comes with credits - enough to
  take a chapter through end to end before you decide anything. After that you
  top up, and only the steps that call a model cost anything.</p>
  <div class="grid g3 rise" style="margin-top:28px">
    <div class="card"><h4>Free credits</h4>
      <p class="mut">On signup. No card. Run a real chapter, not a demo
      page.</p></div>
    <div class="card"><h4>Pay as you go</h4>
      <p class="mut">Credits are spent by the steps that call a model -
      reading, translating, proofreading, and AI cleaning if you turn it
      on.</p></div>
    <div class="card"><h4>Free forever, if you want</h4>
      <p class="mut">Point the steps at your own key or your own local model
      and it costs you nothing here. Finding text, cleaning and typesetting
      never cost credits.</p></div>
  </div>
  <div class="cta" style="margin-top:28px">
    <a class="btn" href="#" data-fill="signup">Create an account</a>
    <a class="btn ghost" href="#" data-fill="contact">Talk to us</a>
    <span class="todo">both links need a URL</span>
  </div>
</div></section>

<section class="band"><div class="wrap">
  <p class="kicker">Questions</p>
  <h2 class="rise">The ones worth answering.</h2>
  <div class="rise" style="margin-top:22px">{faq}</div>
</div></section>

<footer><div class="wrap foot">
  <a class="brand" href="#top">{mark(22)}<span class="wm"><b>Manga</b><i>TCT</i></span></a>
  <span>Translate | clean | typeset.</span>
  <span class="todo">footer links go here</span>
  <span class="built">Built by <b>LMB Technology</b></span>
</div></footer>

<script>
/* Everything below is an ENHANCEMENT. With JS off the page is the whole page:
   every tab panel is reachable, nothing is hidden, and the slider is simply a
   picture. That is why the reveal class starts visible and is hidden by the
   script rather than by the stylesheet. */
document.documentElement.classList.remove('nojs');
(function(){{
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---- the theme control. Three states, two of them stored: "follow the
     system" is the ABSENCE of a stored value rather than a third string, so a
     browser that has never pressed this tracks the operating system for ever.
     lee: *"add light mode and have it fallow teh system default"*. */
  var ORDER = ['auto', 'light', 'dark'];
  var FACE = {{
    auto: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v16.8A8.4 8.4 0 0 0 12 3.6Z" fill="currentColor"/></svg>',
    light: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.6v2M12 19.4v2M2.6 12h2M19.4 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4"/></svg>',
    dark: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 13.5A8.2 8.2 0 0 1 10.5 4a8.2 8.2 0 1 0 9.5 9.5Z"/></svg>'
  }};
  var CALLED = {{auto:'Theme: follows your system', light:'Theme: light',
                dark:'Theme: dark'}};
  var tbtn = document.getElementById('theme');
  function now(){{
    try {{ return localStorage.getItem('tct-theme') || 'auto'; }}
    catch (e) {{ return 'auto'; }}
  }}
  function paint(t){{
    if (!tbtn) return;
    tbtn.innerHTML = FACE[t] || FACE.auto;
    tbtn.title = CALLED[t] || '';
    tbtn.setAttribute('aria-label', CALLED[t] || 'Theme');
  }}
  if (tbtn) {{
    paint(now());
    tbtn.addEventListener('click', function(){{
      var want = ORDER[(ORDER.indexOf(now()) + 1) % ORDER.length];
      try {{
        if (want === 'auto') localStorage.removeItem('tct-theme');
        else localStorage.setItem('tct-theme', want);
      }} catch (e) {{ /* private browsing. It changes, it just forgets. */ }}
      if (want === 'auto') delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = want;
      paint(want);
    }});
  }}

  /* ---- appear on scroll */
  if (!reduce && 'IntersectionObserver' in window) {{
    var io = new IntersectionObserver(function(es){{
      es.forEach(function(e){{
        if (e.isIntersecting) {{ e.target.classList.add('in'); io.unobserve(e.target); }}
      }});
    }}, {{rootMargin: '0px 0px -8% 0px', threshold: 0.05}});
    document.querySelectorAll('.rise').forEach(function(el){{ io.observe(el); }});
  }} else {{
    document.querySelectorAll('.rise').forEach(function(el){{ el.classList.add('in'); }});
  }}

  /* ---- tabs. One handler, both tab strips: they behave identically and a
     second copy of this is a second place for them to stop doing so. */
  function wire(stripId){{
    var strip = document.getElementById(stripId);
    if (!strip) return;
    var tabs = [].slice.call(strip.querySelectorAll('[role=tab]'));
    function show(t){{
      tabs.forEach(function(o){{
        var on = o === t;
        o.setAttribute('aria-selected', on ? 'true' : 'false');
        var p = document.getElementById(o.getAttribute('aria-controls'));
        if (p) p.hidden = !on;
      }});
    }}
    strip.addEventListener('click', function(e){{
      var t = e.target.closest('[role=tab]');
      if (t) show(t);
    }});
    strip.addEventListener('keydown', function(e){{
      var i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      var n = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : -1;
      if (n < 0 || n >= tabs.length) return;
      e.preventDefault(); tabs[n].focus(); show(tabs[n]);
    }});
  }}
  wire('fmttabs'); wire('scrtabs');

  /* ---- the step rail follows the step you are looking at */
  var rail = document.getElementById('rail');
  if (rail && 'IntersectionObserver' in window) {{
    var lis = {{}};
    rail.querySelectorAll('li').forEach(function(li){{ lis[li.dataset.for] = li; }});
    var seen = {{}};
    var so = new IntersectionObserver(function(es){{
      es.forEach(function(e){{ seen[e.target.dataset.step] = e.isIntersecting; }});
      var first = Object.keys(lis).filter(function(k){{ return seen[k]; }})[0];
      Object.keys(lis).forEach(function(k){{
        lis[k].classList.toggle('on', k === first);
      }});
    }}, {{rootMargin: '-45% 0px -45% 0px'}});
    document.querySelectorAll('.step').forEach(function(s){{ so.observe(s); }});
  }}

  /* ---- before / after. The range input IS the control - it is stretched
     over the picture at zero opacity - so dragging, tapping and the arrow
     keys all work without a line of pointer code, and a screen reader gets a
     slider rather than a div. */
  var ba = document.getElementById('ba');
  if (ba) {{
    var r = ba.querySelector('input[type=range]');
    var b = ba.querySelector('.ba-b img');
    function put(){{
      ba.style.setProperty('--x', r.value + '%');
      if (b) b.style.width = ba.clientWidth + 'px';
    }}
    r.addEventListener('input', put);
    addEventListener('resize', put);
    addEventListener('load', put);
    put();
  }}
}})();
</script>
</html>
"""


def standalone(html):
    """Every asset inlined, so the file opens with nothing beside it."""
    def data(path, mime):
        with open(path, "rb") as fh:
            return f"data:{mime};base64," + base64.b64encode(fh.read()).decode()

    html = html.replace("url(assets/anton.ttf) format('truetype')",
                        f"url({data(f'{A}/anton.ttf', 'font/ttf')}) format('truetype')")
    for f in sorted(os.listdir(A)):
        if f.endswith((".jpg", ".png", ".gif", ".svg")):
            mime = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif",
                    "svg": "image/svg+xml"}[f.rsplit(".", 1)[1]]
            html = html.replace(f"assets/{f}", data(f"{A}/{f}", mime))
    return html


def missing(html):
    """Every `assets/…` the page asks for that is not there.

    Asked of the finished HTML rather than of the build, because a picture can
    also be named in a hand-written attribute - and a broken image is the one
    fault a visitor sees before they read a word.
    """
    want = sorted(set(re.findall(r"assets/([A-Za-z0-9_.\-]+)", html)))
    return [f for f in want if not have(f)]


if __name__ == "__main__":
    if not os.path.exists(f"{A}/anton.ttf"):
        raw = base64.b64decode(open(f"{A}/anton.b64").read())
        open(f"{A}/anton.ttf", "wb").write(raw)
    html = build()
    open(f"{HERE}/index.html", "w", encoding="utf-8").write(html)
    open(f"{HERE}/mangatct-site-standalone.html", "w", encoding="utf-8").write(
        standalone(html))
    print("index.html", round(os.path.getsize(f"{HERE}/index.html") / 1e3), "KB")
    print("standalone",
          round(os.path.getsize(f"{HERE}/mangatct-site-standalone.html") / 1e6, 2),
          "MB")
    broken = missing(html)
    if broken:
        # A picture the page asks for and `assets/` does not have goes live as
        # a broken image, which is the one fault a visitor sees before they
        # read a word. Exiting non-zero is what lets the deploy workflow stop
        # on it - an unread warning on a build that succeeded is not a guard.
        print("\nBROKEN image references (should be none):")
        for f in broken:
            print("  ", f)
    if WANTED:
        print(f"\n{len(WANTED)} picture(s) still wanted - each is a labelled "
              "hole on the page:")
        for name, want in WANTED:
            print(f"  {name}\n      {want}")
    # A HOLE is fine - it is a picture lee has not taken yet and it is drawn as
    # such. A BROKEN REFERENCE is not, and this is the difference between the
    # two said out loud, in the exit code, where a machine can read it.
    raise SystemExit(1 if broken else 0)
