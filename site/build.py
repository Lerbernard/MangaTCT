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


def app_version():
    """`__version__`, `CHANNEL` and `SUPPORT` from `../version.py`, read by
    path rather than imported: the site builds in CI with nothing installed,
    and the number on the page has to be the number in the app or it is a
    lie."""
    ns = {}
    with open(os.path.join(os.path.dirname(HERE), "version.py"), encoding="utf-8") as f:
        exec(compile(f.read(), "version.py", "exec"), ns)
    return ns["__version__"], ns.get("CHANNEL", ""), ns.get("SUPPORT", {})


VERSION, CHANNEL, SUPPORT = app_version()
#: Where the site sends people for files. lee: *"there should be no link to
#: github on the website"*. The releases themselves still live on the
#: project's repository - that is where the workflow publishes and where
#: installed copies fetch updates - but every address the site prints is
#: its own: `/get/<version>/<what>` is answered by the `get` Cloud Function
#: (a 302 to the file), `releases.html` lists every version with checksums,
#: and `license.html` carries the GPL. The source offer the license asks
#: for is the app zip, which IS the source.
SOURCE = "/get/latest/app"


# The two glyphs, drawn once. Discord's mark is theirs and used as their brand
# guidelines allow for a "join our server" link; the envelope is nobody's.
DISCORD_SVG = ('<svg viewBox="0 0 24 24" width="17" height="17" fill="currentColor" aria-hidden="true">'
               '<path d="M19.6 5.6A17 17 0 0 0 15.4 4.3l-.2.4a15.5 15.5 0 0 1 3.8 1.9 13.5 13.5 0 0 0-14 0 15.5 15.5 0 0 1 3.8-1.9l-.2-.4a17 17 0 0 0-4.2 1.3C1.8 9.6 1.1 13.5 1.4 17.3a17 17 0 0 0 5.2 2.6l1.1-1.8a11 11 0 0 1-1.7-.8l.4-.3a12.2 12.2 0 0 0 11.2 0l.4.3a11 11 0 0 1-1.7.8l1.1 1.8a17 17 0 0 0 5.2-2.6c.4-4.4-.7-8.3-3-11.7ZM8.7 15c-1 0-1.9-1-1.9-2.1s.8-2.1 1.9-2.1 1.9 1 1.9 2.1S9.7 15 8.7 15Zm6.6 0c-1 0-1.9-1-1.9-2.1s.8-2.1 1.9-2.1 1.9 1 1.9 2.1-.8 2.1-1.9 2.1Z"/>'
               '</svg>')
MAIL_SVG = ('<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" '
            'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="m3.5 7 8.5 6 8.5-6"/></svg>')


def contact_links(cls="btn ghost"):
    """The doors that exist. A door SUPPORT leaves empty is not drawn at
    all - a button to nowhere is exactly what the yellow `todo` chips were
    marking, and drawing one is not an improvement on marking one."""
    out = []
    if SUPPORT.get("discord"):
        # lee: *"add teh discord logo on there too"* - the mark beside the words.
        out.append(f'<a class="{cls} withmark" href="{SUPPORT["discord"]}" target="_blank" '
                   f'rel="noopener">{DISCORD_SVG}Ask on Discord</a>')
    if SUPPORT.get("email"):
        out.append(f'<a class="{cls} withmark" href="mailto:{SUPPORT["email"]}">'
                   f'{MAIL_SVG}Email us</a>')
    return "".join(out)


#: The page in chapters. lee: *"make it not be a long scroll break up the
#: scroll"*, and then *"organisze teh website better so that teer are nt so
#: many tabs and crete sub tave if needed"*. Ten sections that were one long
#: scroll are five chapters, one on screen at a time, and a chapter with more
#: than one part has sub tabs. Every old anchor still lands - `#how`,
#: `#formats`, `#control`, `#rules`, `#compare`, `#credits` - the page opens
#: the chapter and the sub tab it lives in first. With no script at all
#: nothing is hidden: the bars go and the chapters stand one after another.
CHAPTERS = [
    ("how", "How it works", [("how", "Before and after"), ("steps", "The seven steps"),
                             ("screens", "The screens")]),
    ("formats", "Formats", [("formats", "Formats")]),
    ("control", "Your control", [("control", "Editorial control"), ("rules", "Six rules")]),
    ("models", "Models and coins", [("models", "The models"), ("credits", "Coins")]),
    ("compare", "Compare", [("compare", "Compared"), ("faq", "Questions")]),
]

#: What the Product menu says under each chapter's name.
CHAPTER_LINES = {
    "how": "Before and after, the seven steps, the screens",
    "formats": "Manga, manhwa and manhua",
    "control": "Edit every decision, and six rules",
    "models": "The AI you can use, and what it costs",
    "compare": "Against the other ways, and questions",
}


def chapbar():
    """The chapter strip under the hero. The open chapter's tab fills yellow
    and pops. The fill belongs to the tab itself rather than to a highlight
    slid underneath it: a highlight measured a moment too early was narrower
    than its tab, and the dark label ran off it into the dark. With no script
    the whole bar is hidden and the chapters simply follow each other."""
    tabs = "".join(
        f'<button class="ch" role="tab" aria-selected="{str(i == 0).lower()}" '
        f'aria-controls="c-{cid}" id="ct-{cid}"><em>{i + 1:02d}</em>{title}</button>'
        for i, (cid, title, _subs) in enumerate(CHAPTERS))
    return ('<nav class="chapbar" aria-label="Chapters"><div class="wrap">'
            f'<div class="chaps" role="tablist" id="chaptabs">{tabs}</div></div></nav>')


def chap_open(cid):
    """A chapter, and its sub tabs when it has more than one part. The sub tabs
    are folder tabs standing on the panel they open; the open one is drawn by
    its own style, not by a highlight slid under it (see `.subtabs .sb`)."""
    title, subs = next((ti, s) for ch, ti, s in CHAPTERS if ch == cid)
    html = (f'<section class="pan chap" role="tabpanel" id="c-{cid}" '
            f'aria-labelledby="ct-{cid}">')
    if len(subs) > 1:
        html += ('<div class="subbar"><div class="wrap">'
                 f'<div class="subtabs" role="tablist" id="subs-{cid}" aria-label="{title}">'
                 + "".join(
                     f'<button class="sb" role="tab" aria-selected="{str(i == 0).lower()}" '
                     f'aria-controls="{sid}" id="sb-{sid}">{label}</button>'
                     for i, (sid, label) in enumerate(subs))
                 + '</div></div></div>')
    return html


def product_links():
    return "".join(
        f'<a href="#{cid}"><b>{title}</b><span>{CHAPTER_LINES[cid]}</span></a>'
        for cid, title, _subs in CHAPTERS)


# Written out rather than generated, so the source itself carries the link to
# the guide that a test asks of it.
RESOURCE_LINKS = (
    '<a href="tutorial.html"><b>Guide</b><span>Every screen and tool, step by step</span></a>'
    '<a href="fonts.html"><b>Fonts</b><span>The typefaces the app ships with</span></a>'
    '<a href="releases.html"><b>Releases</b><span>Every version, with checksums</span></a>')


def help_links():
    """The Help menu. The Discord and email doors used to be two icons of their
    own on the top bar (lee: *"add thse as button on the top bar so taht they
    are easy to access"*); with the bar cut down to a few menus they live here,
    one press away and with their names written out, beside the privacy page.
    A door SUPPORT leaves empty is still not drawn."""
    out = []
    if SUPPORT.get("discord"):
        out.append(f'<a class="row" href="{SUPPORT["discord"]}" target="_blank" rel="noopener">'
                   f'{DISCORD_SVG}<span class="t"><b>Ask on Discord</b>'
                   '<span>Questions, bugs and requests</span></span></a>')
    if SUPPORT.get("email"):
        out.append(f'<a class="row" href="mailto:{SUPPORT["email"]}">{MAIL_SVG}'
                   f'<span class="t"><b>Email us</b><span>{SUPPORT["email"]}</span></span></a>')
    out.append('<a href="privacy.html"><b>Privacy</b><span>What is kept, and what is not</span></a>')
    return "".join(out)


def menu(label, mid, links, right=False, cls="mgrp"):
    """One menu on the top bar. Hover or keyboard focus opens it with no script
    (the stylesheet); the script adds click, Escape and click-away, which is
    what a phone needs."""
    return (f'<div class="menu {cls}">'
            f'<button class="navb mbtn" type="button" aria-expanded="false" '
            f'aria-controls="{mid}">{label}<i class="car" aria-hidden="true"></i></button>'
            f'<div class="drop{" right" if right else ""}" id="{mid}">{links}</div></div>')


def lmb_mark():
    """The LMB Technology mark beside the credit, when the file is in
    `assets/`. lee: *"add teh logo of lmb thecnology"*. Either `lmb.svg` or
    `lmb.png`; the credit reads fine without it, so a missing file draws
    nothing rather than a hole - a footer is not the place for a WANTED slot.
    """
    for name in ("lmb.svg", "lmb.png"):
        if have(name):
            return f'<img class="lmb" src="assets/{name}" alt="" width="26" height="26">'
    return ""


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
    ("Gemini 3.5 Flash-Lite", "Google", "Default for reading",
     "Cheap and quick. The default for reading text."),
    ("Claude Haiku 4.5", "Anthropic", "Small and careful",
     "Claude's small one. Better at holding a voice than its price suggests."),
    ("Gemini 3.7 Flash", "Google", "Default for translating",
     "Fast, and it thinks before it answers. The default for translating."),
    ("Gemini 3.8 Flash", "Google", "Newest Flash",
     "Google's newest Flash, at the same price as 3.7 Flash."),
    ("Claude Sonnet 5", "Anthropic", "Default for proofreading",
     "The default for proofreading. Catches what the others miss."),
    ("Claude Opus 5", "Anthropic", "Large",
     "Anthropic's large model. Worth it on a page that matters."),
    ("Claude Fable 5", "Anthropic", "Most expensive",
     "The most expensive model on the menu, for the page that has to be right."),
]

STEPS = [
    ("Translation", [
        ("1", "Find text", "Every block of writing on the page, boxed - "
         "dialogue, captions, thoughts on the art, sound effects."),
        ("2", "Read text", "The Japanese, Korean or Chinese out of each box, "
         "read as a close-up of every box. Or read on your own computer, for nothing."),
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
        ("5", "Clean", "The Japanese comes off. A plain white balloon is "
         "filled on your computer; everything else goes to the hosted AI "
         "cleaner, a few coins a chapter."),
        ("6", "Typeset", "The English goes in, fitted to the balloon. Line "
         "breaks first, then size - the words themselves are never touched."),
    ]),
    ("Export", [
        ("7", "Export", "The finished pages. Or the cleaned pages with no "
         "text. Or the original art with every box drawn on, for checking."),
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
        "media": ["manga"],
        "tab": "Manga",
        "lang": "Japanese",
        "dir": "Right to left",
        "line": "The format the rest of it was built around.",
        "imgs": [{"file": "fmt-manga.jpg",
                  "want": "A Japanese page in the editor with the numbered "
                          "boxes on, showing the right-to-left order",
                  "cap": "A Japanese page, every block numbered in reading "
                         "order - right to left, panel by panel."}],
        "good": [
            ("Reading order runs right to left, panel by panel",
             "Boxes are ordered inside their panel first, and the cut is found "
             "by measuring the gutter - including slanted ones, which is most "
             "of an action page. Drag a row and the whole chapter renumbers."),
            ("Can be read locally by manga-ocr, free and offline",
             "It installs with the app and it is the strongest reader there is "
             "for Japanese comic typesetting. Or use the AI reader instead - "
             "that works for all three formats."),
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
        # ONE PANEL FOR BOTH, and it is the code that decided that rather
        # than a missing screenshot.
        #
        # lee: *"so for the mnahua just skip it or jys lump in mnhwa and
        # manhua as one"*. Read out of the app: `STRIP_MEDIA` is the set
        # `{manhwa, manhua}`; `MEDIA` gives both `rtl: False`; `LANG_ENGINE`
        # sends both to easyocr; `BIG_SFX_BY_MEDIUM` overrides manga alone
        # and lets manhua keep the webtoon number. The only thing that
        # actually differs is the language and which of the two webtoon
        # balloon models is the default - and either card can be picked on
        # either format.
        #
        # Three tabs claimed a distinction the app does not make, and the
        # old manhua panel said so itself: three of its four strengths and
        # all three of its rough edges read "the same as manhwa". What is
        # genuinely Chinese is kept below; what was repetition is gone.
        "id": "webtoon",
        "media": ["manhwa", "manhua"],
        "tab": "Manhwa &amp; manhua",
        "lang": "Korean | Chinese",
        "dir": "Left to right",
        # Two pictures, one panel. The claim this panel makes is "one route,
        # two languages", and two chapters side by side is the only way to
        # SHOW that rather than assert it - a Korean chapter the app cut into
        # pages itself, and a Chinese one it found the text on.
        "imgs": [
            {"file": "fmt-manhwa.jpg",
             "want": "A Korean webtoon chapter after the strip was re-cut - "
                     "the page list down the side showing the new pages",
             "alt": "A Korean webtoon chapter in the editor",
             "cap": "Korean. The eight pages down the side are the ones the "
                    "app cut for itself out of twelve machine-sliced files."},
            {"file": "fmt-manhua.jpg",
             "want": "A Chinese page mid-chapter, ideally one with a dense "
                     "caption box, in the Translation view",
             "alt": "A Chinese manhua chapter in the editor",
             "cap": "Chinese, same route, same screen: 41 pages found, all "
                    "three kinds of block on this one."},
        ],
        "line": "One route, two languages. Webtoon strips are cut into pages "
                "before anything else runs.",
        "good": [
            ("A sliced strip is cut back into pages, on upload",
             "Upload the tiles a site hands you and they are re-cut into "
             "pages - always at a gutter, never through the artwork, and your "
             "original files are kept beside the chapter. A page that is "
             "still the wrong length you cut yourself, with Cut / join."),
            ("Register reaches the model, in both languages",
             "Korean: \ud574\uc694\uccb4, \ud574\uccb4 and \ud569\uc1fc\uccb4, and "
             "\uc624\ube60 / \uc5b8\ub2c8 / \uc120\ubc30. Chinese: \u54e5, \u59d0, \u524d\u8f88 and the "
             "classical phrasing that marks a formal voice. The register notes "
             "go into the prompt with the page, so politeness is not flattened "
             "into one English voice."),
            ("Simplified Chinese read locally, traditional through a model",
             "The local reader is set to simplified. A vision model reads "
             "either, and needs nothing installed."),
            ("Left to right, and it is a setting",
             "Direction follows the format by default and you can override it "
             "per chapter."),
        ],
        "rough": [
            ("Chinese has had one chapter, Korean has had many",
             "One code path with the language swapped, and both ends of it "
             "have now been run on real pages: several Korean chapters, and "
             "one 41-page manhua - 86 blocks found, 63 balloons, 21 sound "
             "effects, and the single page with no writing on it correctly "
             "given no boxes. That is a chapter, not a body of evidence. The "
             "Korean side has had far more of both our attention and our "
             "measurements, and where the two differ it is the Chinese one "
             "that is less proven."),
            ("The local Korean and Chinese reader is an extra install",
             "Both are read locally by easyocr, which does not come with the "
             "app: <code>pip install easyocr</code>. Or point Read text at a "
             "vision model and skip it entirely - that path needs nothing "
             "installed."),
            ("The reading prompt still carries Japanese instructions",
             "Rules about furigana and small kana are sent with a Korean or "
             "Chinese page too. Harmless in practice, and honestly just not "
             "written yet."),
            ("The name and honorific audit knows Japanese suffixes only",
             "-ssi, -nim, \uc624\ube60, -ge and -jie are handled by the translator "
             "and NOT by the check that runs afterwards, so a drift in a "
             "romanised Korean or Chinese name is not caught for you."),
            ("Export is one file per page",
             "Nothing stitches the strip back into one long image. You get the "
             "pages the re-cut made."),
        ],
    },
]

# The screens, in the order the app shows them. Home first, because it is
# what the app opens on. lee: *"upadet the website to be accurate with whats
# acculy on teh app"*. Its picture is the app signed out with nothing opened
# yet - what somebody who has just installed it sees.
TABS = [
    ("Home", "Where the app opens: start a new project or open a project "
     "file, sign in, and pick up the chapters you opened before.",
     "ui-home-real.jpg", "The Home screen of a new install"),
    ("File","Open a chapter, add pages, reorder them. One screen, one job.",
     "ui-pages.jpg", "The File screen: what the chapter is, what it is "
     "written in, and where the pages come from"),
    ("Workspace", "The page. Boxes on the left of the split, typesetting on "
     "the right, every tool down the rail. This is where the work happens.",
     "ui-translation-real.jpg", "The workspace on a real page"),
    ("Results", "The proofread report and the chapter audit - what the second "
     "pass found, page by page, with the original beside it.",
     "ui-results-real.jpg",
     "The Results tab showing the proofread report on your own chapter"),
    ("Settings", "The story, languages, detection and reading, AI models, "
     "cleaning, fonts, your account and updates.", "ui-settings-fonts-real.jpg",
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
    ("Nothing is uploaded without a step that says so.",
     "Finding text, typesetting and exporting run on your computer. Reading, "
     "translating, proofreading and cleaning send only what that step needs, "
     "through MangaTCT, to the service doing it."),
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
    ("Every bubble, and how it was cleaned",
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
     "fixed", "per step, from five AI companies"),
    ("Translate it entirely by hand", "yes", "no",
     "yes - a labelled file out, filled in, back"),
    ("Webtoon strips cut into pages", "you cut them", "rarely",
     "on upload, at the gutters"),
    ("Your own cleaned pages", "they are yours", "rarely", "drop them in"),
]

FAQ = [
    ("What do I need to run it?",
     "Windows 10 or 11. The installer brings its own Python, and the first "
     "start downloads the text models - about 300 MB, once. No graphics card "
     "needed. Reading, translating, proofreading and the hosted cleaner are "
     "paid in TCT Coins; finding text, typesetting and exporting run offline."),
    ("Does it upload my raws?",
     "Finding text, typesetting and exporting never leave your machine. "
     "Reading, translating and proofreading send the page, or its text, "
     "through MangaTCT to the AI company you picked. Cleaning sends the parts "
     "of a page that are not plain white balloons to the hosted cleaner. Read "
     "on your computer, translate by hand and stay signed out, and nothing "
     "leaves at all."),
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
     "upload it back - or type straight into the page. Sign out and cleaning "
     "uses the local fill too."),
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
        f'<div>'
        # `pic`, not `i` - the outer comprehension is already using `i` for
        # the tab index, and shadowing it here hides every panel but the first.
        + "".join(
            f'<figure class="shot pan-img" style="margin-bottom:26px">'
            f'{slot(pic["file"], pic.get("alt") or f["tab"] + " in the editor", pic["want"], "16 / 10")}'
            f'<figcaption>{pic["cap"]}</figcaption></figure>'
            for pic in f["imgs"])
        # The "Where it is rough" box that stood here is GONE from the page.
        # lee: *"reove this and anything like it it the user does not need to
        # know this"*. The `rough` lists stay in FORMATS as the engineering
        # record - they are what a limitation gets written into when it is
        # found, and two tests still hold them honest - but they are not
        # rendered. The one item in them a person genuinely needed before
        # installing (Korean and Chinese need `pip install easyocr`) moved to
        # the guide's Detection & OCR screen, where somebody looking for it
        # will actually be.
        + "</div></div></section>"
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
    # Three PORTRAIT screenshots - the editor's side rails, 336x905 - so
    # three columns, picture on top, words under it. They used to be three
    # stacked rows, each a four-line paragraph beside a tall picture in a
    # 4:3 hole, and every row was mostly air. lee: *"chnahge teh layout ...
    # so taht the vertcal screenshot are better integated"*. The picture is
    # capped and fades out at the bottom rather than shown whole: a rail is
    # 905px tall and three of those side by side is the "long screenshot"
    # he asked not to have. The top is where the controls are.
    control = ('<div class="ctl3 rise">' + "".join(
        f'<div class="ctlcol">'
        f'<figure class="shot rail">{slot(img, t, want, "336 / 520")}</figure>'
        f'<h3>{t}</h3><p>{d}</p></div>'
        for t, d, img, want in CONTROL) + '</div>')
    rows = "".join(
        f"<tr><th>{a}</th><td>{b}</td><td>{c}</td><td class=\"me\">{d}</td></tr>"
        for a, b, c, d in COMPARE)
    faq = "".join(f"<details><summary>{q}</summary><p>{a}</p></details>"
                  for q, a in FAQ)

    # FOUR before/after handles in a row, each a quarter of the width, not
    # one the width of the page. lee: *"this is too big and do a mahwa page
    # too and othe r pages 4 in total in a smaller spot"*. Every pair is one
    # page twice - the raw scan and the finished export, same size - so the
    # handle reveals the English under the Japanese with nothing moving.
    # Both halves have to exist for a pair to mean anything. A pair that is
    # not there yet is simply not drawn - the row is three wide until the
    # fourth arrives - rather than a labelled hole on the front page of a
    # live site. The manhwa pair (`ba4-*`) is the one still owed: lee's
    # webtoon chapter, exported from the app, raw beside finished.
    PAIRS = [("ba", "manga"), ("ba2", "manga"), ("ba3", "manga"), ("ba4", "manhwa")]

    def one_ba(tag, what):
        b, a = f"{tag}-before.jpg", f"{tag}-after.jpg"
        return (f'<div class="ba">'
                f'<img class="ba-a" src="assets/{b}" alt="A raw {what} page">'
                f'<div class="ba-b"><img src="assets/{a}" '
                f'alt="The same {what} page, cleaned and typeset in English"></div>'
                f'<div class="ba-h" aria-hidden="true"><i></i></div>'
                f'<input type="range" min="0" max="100" value="52" step="0.1" '
                f'aria-label="Reveal the typeset {what} page"></div>')

    cells = [one_ba(t, w) for t, w in PAIRS
             if have(f"{t}-before.jpg") and have(f"{t}-after.jpg")]
    ba = (f'<div class="ba4" style="grid-template-columns:repeat({len(cells)},1fr)">'
          + "".join(cells) + '</div>')

    return f"""<!doctype html>
<html lang="en" class="nojs">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MangaTCT Beta - translate, clean, typeset</title>
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
/* Every anchored section has to clear the sticky header AND the chapter bar
   under it, or following a link lands with the heading tucked underneath. */
[id]{{scroll-margin-top:128px}}
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
.hd{{display:flex;align-items:center;gap:14px;height:56px}}
.brand{{display:flex;align-items:flex-end;gap:9px;text-decoration:none;color:inherit}}
.brand svg{{display:block}}
/* MangaTCT is one word. `gap` on a flex row falls between EVERY child, so the
   space meant to sit between the mark and the name was also splitting the
   name in half. */
.brand .wm{{display:flex;align-items:flex-end;gap:0}}
/* THE APP IS IN BETA and says so wherever it says its own name.
   lee: "make the app be in beta ... mae ecrything say beta". One small pill
   beside the wordmark, the same one the editor's header wears. */
.brand .betapill{{font:700 8px/1 system-ui;letter-spacing:.06em;
  font-style:normal;color:#0f1218;background:#ffc400;border-radius:7px;
  padding:2px 4px 1.5px;margin-left:5px;align-self:center;
  text-transform:uppercase}}
.brand b{{font-size:20px;line-height:.82}}
.brand i{{font-size:20px;line-height:.82;color:var(--accent);font-style:normal}}
.hd nav{{margin-left:auto;display:flex;gap:5px;font-size:13px;
 align-items:center;flex-wrap:nowrap;min-width:0}}
/* Pills, not a row of words. Six links in a line all the same colour read as
   one sentence you cannot press. */
.hd nav a,.navb{{color:var(--dim);text-decoration:none;padding:6px 10px;
 border:1px solid transparent;border-radius:999px;line-height:1;
 white-space:nowrap;background:var(--panel2);font:inherit;font-size:13px;
 font-weight:600;cursor:pointer;display:inline-flex;align-items:center;
 gap:7px;transition:color .15s ease,border-color .15s ease,
 background .15s ease,transform .15s ease}}
.hd nav a:hover,.navb:hover{{color:var(--fg);border-color:transparent;
 background:var(--line);transform:translateY(-1px)}}
.navb.icon{{padding:6px;width:30px;height:30px;justify-content:center;
 color:var(--dim)}}
.navb svg{{display:block}}
.btn{{display:inline-block;background:linear-gradient(160deg,var(--accent),var(--accent2));
 color:var(--on-accent);padding:12px 21px;border-radius:10px;font-weight:700;
 text-decoration:none;font-size:15px;border:0;white-space:nowrap;
 transition:transform .18s cubic-bezier(.2,.8,.2,1),box-shadow .18s ease,filter .18s ease,
 background .18s ease}}
/* The two in the header are smaller than the ones in the page body. */
.hd .btn{{padding:9px 15px;font-size:13.5px;border-radius:9px}}
.btn:hover{{filter:brightness(1.07);transform:translateY(-2px);box-shadow:0 10px 26px var(--glow)}}
.btn.ghost{{background:var(--panel2);color:var(--fg)}}
.btn.withmark{{display:inline-flex;align-items:center;gap:9px}}
.btn.withmark svg{{flex:none}}
.btn.ghost:hover{{background:var(--line);box-shadow:0 10px 26px rgba(0,0,0,.22)}}

/* ------------------------------------------------------------------ hero */
.hero{{padding:clamp(56px,7vw,92px) 0 0;position:relative;overflow:hidden}}
.hero:before{{content:"";position:absolute;inset:-30% 30% 55% -10%;
 background:radial-gradient(closest-side,var(--glow),transparent 70%);
 pointer-events:none;animation:drift 16s ease-in-out infinite alternate}}
@keyframes drift{{from{{transform:translate(0,0) scale(1)}}to{{transform:translate(18%,12%) scale(1.15)}}}}
.hero .wrap{{position:relative}}
.hero h1{{font-size:clamp(38px,5.2vw,66px);margin:0 0 18px;max-width:24ch}}
.hero h1 em{{font-style:normal;
 background:linear-gradient(96deg,var(--accent),var(--accent2));
 -webkit-background-clip:text;background-clip:text;color:transparent}}
.hero .lead{{font-size:19.5px;max-width:60ch}}
.cta{{display:flex;gap:12px;flex-wrap:wrap;margin:28px 0 10px;align-items:center}}
.note{{color:var(--dim2);font-size:13.5px}}
.heroshot{{margin-top:44px;border:1px solid var(--line);border-radius:var(--r);
 overflow:hidden;background:var(--panel);box-shadow:var(--shadow);
 transition:transform .3s ease-out;will-change:transform}}
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
 color:var(--accent);background:var(--glow);border-radius:999px;
 padding:3px 10px;margin-bottom:9px}}
.ai p{{margin:0;color:var(--dim);font-size:14px}}

/* A step that is a choice says so in the heading, not in a footnote. */
.opt{{font-family:inherit;font-size:11px;letter-spacing:.1em;
 text-transform:uppercase;font-weight:700;color:var(--accent);
 background:var(--glow);border-radius:999px;padding:3px 9px;
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
.ba4{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}
/* Every cell is the shape of a manga page, whatever is in it: a taller
   manhwa page is cropped to its top rather than making its column taller
   than the other three. Same rule as the rails in Editorial control. */
.ba{{aspect-ratio:960 / 1365}}
.ba{{position:relative;border:1px solid var(--line);border-radius:var(--r);
 overflow:hidden;background:var(--panel);touch-action:none;
 box-shadow:0 18px 50px rgba(0,0,0,.45)}}
.ba img{{width:100%;height:100%;object-fit:cover;object-position:top;display:block}}
.ba-b{{position:absolute;inset:0;width:var(--x,52%);overflow:hidden}}
.ba-b img{{position:absolute;top:0;left:0;height:100%;width:auto;
 max-width:none}}
.ba-h{{position:absolute;top:0;bottom:0;left:var(--x,52%);width:2px;
 background:var(--accent);transform:translateX(-1px);pointer-events:none}}
.ba-h i{{position:absolute;top:50%;left:50%;width:32px;height:32px;
 margin:-16px 0 0 -16px;border-radius:50%;background:var(--accent);
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
.tb{{appearance:none;background:var(--panel2);color:var(--dim);
 border:0;border-radius:999px;padding:10px 19px;
 font:inherit;font-size:15px;font-weight:600;cursor:pointer;
 display:flex;align-items:baseline;gap:8px;
 transition:color .18s ease,background .18s ease,transform .18s cubic-bezier(.2,.8,.2,1),
 box-shadow .18s ease}}
.tb span{{font-size:12px;font-weight:400;color:var(--dim2)}}
.tb:hover{{color:var(--fg);background:var(--line);transform:translateY(-2px)}}
.tb[aria-selected=true]{{color:#141821;
 background:linear-gradient(160deg,var(--accent),var(--accent2));box-shadow:0 8px 22px var(--glow)}}
.tb[aria-selected=true]:hover{{color:#141821;filter:brightness(1.06)}}
.tb[aria-selected=true] span{{color:#4a3d00}}
.pan[hidden]{{display:none}}
.pan-img img{{max-height:330px;object-fit:cover;object-position:top}}
.pantop{{align-items:start}}
.pantop .chips{{margin-bottom:34px}}
.pantop .sub{{margin-top:0}}
.panlead{{color:var(--dim);font-size:17px;margin:0 0 12px}}
.chips{{display:flex;gap:8px;flex-wrap:wrap;margin:0}}
.chip{{background:var(--panel2);border-radius:999px;padding:5px 13px;
 font-size:12.5px;color:var(--dim)}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:36px}}
.two.tight{{grid-template-columns:1fr 1.15fr;align-items:center}}
.sub{{font-size:11.5px;letter-spacing:.2em;text-transform:uppercase;
 font-weight:700;margin:0 0 16px}}
.sub.good{{color:var(--ok)}}
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
.ctl3{{display:grid;grid-template-columns:repeat(3,1fr);gap:26px;align-items:start}}
.ctlcol h3{{margin:16px 0 6px;font-size:19px}}
.ctlcol p{{color:var(--dim);margin:0;font-size:15px}}
/* The rail, cropped to its top and faded out, never scaled past its own
   pixels - 336 wide is what it is, so it sits centred in its column crisp. */
figure.shot.rail{{position:relative;max-width:336px;margin:0 auto;height:520px;
 overflow:hidden;border-radius:var(--r);border:1px solid var(--line)}}
figure.shot.rail img{{width:100%;height:100%;object-fit:cover;object-position:top;
 border:0;border-radius:0;display:block}}
figure.shot.rail .slot{{height:100%}}
figure.shot.rail:after{{content:"";position:absolute;left:0;right:0;bottom:0;
 height:110px;background:linear-gradient(to bottom,transparent,var(--bg));
 pointer-events:none}}
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

footer{{border-top:1px solid var(--line);padding:52px 0 40px;color:var(--dim);
 font-size:14px;background:var(--bg2)}}
.foot{{display:grid;grid-template-columns:1.6fr 1fr 1fr;gap:40px;align-items:start}}
.footabout p{{margin:14px 0 0;max-width:38ch;font-size:14.5px;line-height:1.55;color:var(--dim)}}
.footlinks b{{display:block;font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--dim2);margin-bottom:4px;font-weight:700}}
.footlinks a svg{{width:15px;height:15px;flex:none;opacity:.85}}
.footbar{{display:flex;justify-content:space-between;align-items:center;gap:18px;
 margin-top:40px;padding-top:22px;border-top:1px solid var(--line);
 font-size:13px;color:var(--dim2);flex-wrap:wrap}}
.built{{display:inline-flex;align-items:center;gap:9px;color:var(--dim2);
 text-decoration:none;padding:8px 12px;border-radius:10px;border:1px solid transparent}}
.built:hover{{background:var(--panel2);color:var(--dim)}}
.built img.lmb{{display:block;width:26px;height:26px;border-radius:7px}}
.built b{{color:var(--fg);font-weight:650}}
/* The footer links. They replaced a placeholder chip, so every one of them
   goes somewhere real - and the two that depend on doors lee has not built
   yet are drawn by `contact_links` only once they exist. */
.footlinks{{display:flex;flex-direction:column;gap:9px}}
.footlinks a{{color:var(--dim);text-decoration:none;display:inline-flex;align-items:center;
 gap:8px;width:fit-content;border-bottom:1px solid transparent;font-size:14.5px}}
.footlinks a:hover{{color:var(--fg);border-bottom-color:var(--accent)}}
.foot .brand b,.foot .brand i{{font-size:20px}}
@media(max-width:980px){{
 .walk{{grid-template-columns:1fr;gap:24px}}
 .walk .rail{{position:static}}
 .walk .rail ol{{display:flex;gap:8px;overflow-x:auto;padding-bottom:6px}}
 .walk .rail li{{border-left:0;border-bottom:2px solid var(--line);
  padding:6px 10px 8px;white-space:nowrap}}
 .walk .rail li.on{{border-bottom-color:var(--accent)}}
 .pantop,.two,.two.tight,.ctl3,.g3,.g2,.clips,.gsteps{{grid-template-columns:1fr}}
 .foot{{grid-template-columns:1fr 1fr;gap:28px}} .footabout{{grid-column:1 / -1}}
 .ba4{{grid-template-columns:1fr 1fr!important}}
 .ais{{grid-template-columns:1fr}}
 /* The three menus and Pricing fold into one Menu; the theme control stays.
    Hiding the whole nav took the theme button with it, which is the one thing
    on this bar a phone is MORE likely to want than a desktop. */
 .hd nav .menu.mgrp,.hd nav>a.top{{display:none}}
 .hd nav .menu.all{{display:block}}
 .ch{{padding:9px 13px;font-size:14px}}
 .hd nav{{gap:6px}}
}}
@media(max-width:560px){{
 .hd{{height:auto;padding:10px 0;flex-wrap:wrap;gap:10px}}
 .stats{{gap:22px}}
 .cta .btn{{width:100%}}
}}

/* ------------------------------------------------- the top bar, organised
   lee: *"organisze teh website better so that teer are nt so many tabs and
   crete sub tave if needed"*. A few things across the top instead of eleven:
   Product, Resources and Help open menus, Pricing is a link. The thin bar along
   the top edge is how far down the page you are. */
.progress{{position:absolute;left:0;right:0;top:0;height:2px;transform-origin:0 50%;
 transform:scaleX(0);background:linear-gradient(90deg,var(--accent),var(--accent2));
 pointer-events:none;z-index:2}}
.menu{{position:relative}}
.mbtn .car{{width:6px;height:6px;border-right:1.6px solid currentColor;
 border-bottom:1.6px solid currentColor;transform:translateY(-2px) rotate(45deg);
 transition:transform .22s ease;margin-left:3px;display:inline-block}}
.menu.open .car,.menu:hover .car{{transform:translateY(1px) rotate(225deg)}}
.drop{{position:absolute;top:calc(100% + 10px);left:0;min-width:300px;padding:6px;
 background:var(--panel);border-radius:14px;box-shadow:var(--shadow);
 display:flex;flex-direction:column;gap:2px;z-index:70;
 opacity:0;visibility:hidden;transform:translateY(-8px) scale(.98);transform-origin:top left;
 transition:opacity .18s ease,transform .22s cubic-bezier(.2,.8,.2,1),visibility 0s linear .22s}}
.drop.right{{left:auto;right:0;transform-origin:top right}}
.drop:before{{content:"";position:absolute;left:0;right:0;top:-12px;height:12px}}
.menu:hover .drop,.menu:focus-within .drop,.menu.open .drop{{opacity:1;visibility:visible;
 transform:none;transition:opacity .18s ease,transform .22s cubic-bezier(.2,.8,.2,1),visibility 0s}}
/* A menu row is a row, not a pill. lee: *"not a big fan of this it lloks ugly
   cnag ethe digning to smothing else"* - the header's own link style (a grey
   pill, centered, one line) was reaching into the menus and turning every
   entry into a fat grey capsule. These rules are scoped to the menus so it
   cannot: left-aligned, a name and one line under it, nothing behind them
   until the pointer arrives - then a soft fill and a yellow bar slide in. */
.hd nav .drop a{{display:grid;grid-template-columns:1fr;row-gap:3px;align-items:start;
 justify-items:start;text-align:left;padding:10px 14px 10px 16px;border:0;border-radius:10px;
 background:transparent;color:var(--fg);font-size:14px;line-height:1.3;white-space:normal;
 position:relative;transform:none;
 transition:background .16s ease,padding-left .22s cubic-bezier(.2,.8,.2,1)}}
.hd nav .drop a:before{{content:"";position:absolute;left:6px;top:11px;bottom:11px;width:3px;
 border-radius:2px;background:linear-gradient(var(--accent),var(--accent2));
 transform:scaleY(0);transition:transform .22s cubic-bezier(.2,.8,.2,1)}}
.hd nav .drop a b{{color:var(--fg);font-weight:650;font-size:14px}}
.hd nav .drop a span{{color:var(--dim);font-size:12.5px;font-weight:400}}
.hd nav .drop a.row{{grid-template-columns:auto 1fr;column-gap:12px;align-items:center}}
.hd nav .drop a.row .t{{display:grid;row-gap:3px}}
.hd nav .drop a svg{{color:var(--accent)}}
.hd nav .drop a:hover,.hd nav .drop a:focus-visible{{background:var(--panel2);
 padding-left:22px;transform:none;color:var(--fg)}}
.hd nav .drop a:hover:before,.hd nav .drop a:focus-visible:before{{transform:scaleY(1)}}
.menu.all .drop{{max-height:calc(100vh - 90px);overflow-y:auto}}
/* On a phone the one Menu opens as a panel under the bar, the width of the
   screen less a margin. Anchored to its button it was wider than the room to
   the button's left, and the first letters of every line were off the screen. */
@media(max-width:980px){{
 .menu.all .drop{{position:fixed;left:12px;right:12px;top:calc(var(--hh,60px) + 6px);
  min-width:0;transform-origin:top center}}
}}
.menu.all{{display:none}}

/* ---------------------------------------------------------------- chapters
   lee: *"make it not be a long scroll break up the scroll"*. One chapter on
   screen at a time; the open one's tab fills yellow and pops, and the new
   chapter slides in from the side it is on. */
.chapbar{{position:sticky;top:var(--hh,56px);z-index:55;background:var(--bg);
 border-bottom:1px solid var(--line);backdrop-filter:blur(12px) saturate(1.3)}}
.chaps,.subtabs{{position:relative;display:flex;gap:4px;overflow-x:auto;scrollbar-width:none}}
.chaps::-webkit-scrollbar,.subtabs::-webkit-scrollbar{{display:none}}
.chaps{{padding:8px 0}}
.ch,.sb{{appearance:none;border:0;background:transparent;color:var(--dim);font:inherit;
 font-weight:650;cursor:pointer;white-space:nowrap;position:relative;z-index:1;
 transition:color .22s ease,transform .18s cubic-bezier(.2,.8,.2,1)}}
/* flex:none - the chapter tabs had the sub tabs' fault: overflow:hidden (the
   ripple) let the row squeeze every tab below its label on a phone, and all
   five names were cut off. They keep their width and the row scrolls, which
   it was always meant to (the open chapter is scrolled into view). */
.ch{{flex:none;padding:10px 17px;border-radius:12px;font-size:15px;display:inline-flex;gap:9px;
 align-items:baseline;overflow:hidden}}
.ch em{{font-style:normal;font-size:11.5px;color:var(--dim2);letter-spacing:.08em;
 transition:color .22s ease}}
.ch:hover,.sb:hover{{color:var(--fg)}}
.ch[aria-selected=true]{{color:var(--on-accent);background:linear-gradient(160deg,var(--accent),var(--accent2));
 box-shadow:0 8px 24px var(--glow);animation:pop .34s cubic-bezier(.2,.8,.2,1)}}
@keyframes pop{{from{{transform:scale(.9)}}to{{transform:none}}}}
.ch[aria-selected=true] em{{color:var(--on-accent)}}
/* The sub tabs are folder tabs. lee: *"fix these one teh website to they are
   clipping into eacother  make the like folder stckoit and one iteam   like
   this"* - with a photo of paper folders, a tab sticking up from the top edge
   of each sheet.

   They clipped because every tab carries overflow:hidden (it keeps the press
   ripple inside the tab), and a flex item with overflow hidden is allowed to
   shrink to nothing. On a narrow screen the strip, held to the width of the
   column, squeezed each tab below the width of its own label instead of
   scrolling: the words were cut off at the tab's edge, and the dark highlight
   slid underneath the open tab ran straight into the cut-off words beside it.
   So a tab never shrinks below its label now - on a wide screen it does not
   shrink at all, on a phone its label may break onto a second line but never
   narrower than its longest word - and there is no highlight to slide and
   measure. The open tab IS the top of its panel: the panel's ground, the
   panel's edge line running up its sides and over its top, and nothing drawn
   between them, so tab and panel read as one sheet. The closed tabs sit a
   little lower and a shade apart, tucked behind it. Both are the same size
   (the edge is a border on every tab, transparent on the closed ones), so
   opening a tab never moves its neighbours. */
.subbar{{padding:26px 0 0;position:relative;z-index:2;margin-bottom:-1px}}
.subtabs{{align-items:stretch;gap:6px;padding-top:4px}}
.subtabs .sb{{flex:none;margin:5px 0 1px;padding:9px 20px 11px;font-size:14px;overflow:hidden;
 border:1px solid transparent;border-bottom:0;border-radius:12px 12px 0 0;transform-origin:50% 100%;
 background:var(--panel2);background:color-mix(in srgb,var(--fg) 7%,var(--bg));
 box-shadow:inset 0 -7px 8px -8px rgba(0,0,0,.26);
 transition:color .22s ease,background-color .22s ease,margin .26s cubic-bezier(.2,.8,.2,1),
 transform .18s cubic-bezier(.2,.8,.2,1)}}
.subtabs .sb:hover{{color:var(--fg);background:color-mix(in srgb,var(--fg) 11%,var(--bg))}}
.subtabs .sb[aria-selected=true]{{color:var(--fg);background:var(--bg2);border-color:var(--line2);
 margin:0;box-shadow:none}}
.subtabs .sb[aria-selected=true]:before{{content:"";position:absolute;left:12px;right:12px;top:0;
 height:2px;border-radius:0 0 2px 2px;background:linear-gradient(90deg,var(--accent),var(--accent2))}}
.subtabs .sb:focus-visible{{outline-offset:-4px}}
/* The sheet the tabs stand on. The subbar overlaps it by the one pixel of its
   edge line, and the open tab reaches the bottom of the subbar, so the line
   runs under every closed tab and stops where the open one joins. Every panel
   under a sub tab strip is the same ground: only one of them is ever on screen,
   so the alternating grounds of the bands had nothing to tell apart here -
   except with no script, where the strip is gone, every panel shows, and the
   bands alternate as before. */
html:not(.nojs) .subbar~.spn{{background:var(--bg2);border-top:1px solid var(--line2)}}
@media(max-width:560px){{
 .subtabs{{gap:4px}}
 .subtabs .sb{{flex:0 1 auto;min-width:min-content;white-space:normal;text-align:center;
  padding:8px 12px 10px;font-size:13.5px;line-height:1.3}}
}}
.nojs .chapbar,.nojs .subbar{{display:none}}
.chap>.band:first-of-type{{border-top:0}}
@keyframes panIn{{from{{opacity:0;transform:translateX(calc(var(--dir,1) * 28px))}}
 to{{opacity:1;transform:none}}}}
.pan.enter{{animation:panIn .44s cubic-bezier(.2,.8,.2,1) both}}

/* -------------------------------------------------------- the page, alive
   lee: *"make teh website moreinterractive and add animaation and makethe
   website dynamoic and add better on hover animation and on click animationa
   nd remove this faint outline on these on te button s on teh website"*.
   Fills instead of outlines; a lift and a glow on hover; a press and a ripple
   on click; a light that follows the pointer across a card. The focus ring
   stays - it is how somebody on a keyboard knows where they are. */
.btn,.tb,.navb{{position:relative;overflow:hidden}}
.btn:active,.tb:active,.navb:active,.ch:active,.sb:active{{transform:scale(.95)}}
.rip{{position:absolute;border-radius:50%;pointer-events:none;background:currentColor;
 opacity:.22;transform:scale(0);animation:rip .6s ease-out forwards}}
@keyframes rip{{to{{transform:scale(1);opacity:0}}}}
.spot{{position:relative;overflow:hidden}}
.spot:after{{content:"";position:absolute;inset:0;pointer-events:none;opacity:0;
 background:radial-gradient(280px circle at var(--mx,50%) var(--my,50%),var(--glow),transparent 65%);
 transition:opacity .3s ease}}
.spot:hover:after{{opacity:1}}
.card,.rule,.clip{{transition:transform .22s cubic-bezier(.2,.8,.2,1),border-color .22s ease,box-shadow .22s ease}}
.card:hover,.rule:hover,.clip:hover{{transform:translateY(-4px);border-color:var(--line2);
 box-shadow:0 18px 40px rgba(0,0,0,.25)}}
.ai:hover,.step:hover{{box-shadow:0 18px 40px rgba(0,0,0,.25)}}
@keyframes heroIn{{from{{opacity:0;transform:translateY(20px)}}to{{opacity:1;transform:none}}}}
.hero .wrap>*{{animation:heroIn .75s cubic-bezier(.2,.8,.2,1) backwards}}
.hero .wrap>*:nth-child(2){{animation-delay:.07s}}
.hero .wrap>*:nth-child(3){{animation-delay:.14s}}
.hero .wrap>*:nth-child(4){{animation-delay:.21s}}
.hero .wrap>*:nth-child(5){{animation-delay:.26s}}
.hero .wrap>*:nth-child(6){{animation-delay:.32s}}
.hero .wrap>*:nth-child(7){{animation-delay:.4s}}
.hero h1 em{{background-size:200% 100%;animation:shine 6s ease-in-out infinite alternate}}
@keyframes shine{{from{{background-position:0 0}}to{{background-position:100% 0}}}}
@media(prefers-reduced-motion:reduce){{
 .hero:before,.hero .wrap>*,.hero h1 em,.pan.enter,.rip,.ch[aria-selected=true]{{animation:none}}
 .drop,.subtabs .sb,.btn,.tb,.ch,.sb,.card,.rule,.clip{{transition:none}}
 .heroshot{{transition:none;transform:none!important}}
}}
</style>

<header><div class="progress" id="progress" aria-hidden="true"></div><div class="wrap hd">
  <a class="brand" href="#top">{mark(24)}<span class="wm"><b>Manga</b><i>TCT</i></span><em class="betapill">BETA</em></a>
  <nav aria-label="Site">
    {menu("Product", "m-product", product_links())}
    {menu("Resources", "m-res", RESOURCE_LINKS)}
    <a class="navb top" href="pricing.html">Pricing</a>
    {menu("Help", "m-help", help_links(), right=True)}
    {menu("Menu", "m-all", product_links() + RESOURCE_LINKS + '<a href="pricing.html"><b>Pricing</b><span>Coin packs, and what a chapter costs</span></a>' + help_links(), right=True, cls="all")}
    <button class="navb icon" id="theme" type="button"></button>
  </nav>
  <a class="btn ghost" href="signin.html">Sign in</a>
  <a class="btn" href="download.html">Download</a>
</div></header>

<a id="top"></a>

<section class="hero"><div class="wrap">
  <p class="kicker">Manga | manhwa | manhua</p>
  <h1>Translate, clean and typeset a chapter <em>with full control of every page</em></h1>
  <p class="lead">MangaTCT finds every block of text, reads it, translates it
  with your glossary and your character sheet, wipes the original off the art
  and sets the English back into the balloon. Then it hands you all of it:
  every line, every block, every bubble, down to the outline colour.</p>
  <div class="cta">
    <a class="btn" href="download.html">Download for Windows - free</a>
    <a class="btn ghost" href="#how">See it work</a>
  </div>
  <p class="note">Windows 10 and 11. Version {VERSION}{" (" + CHANNEL + ")" if CHANNEL else ""}.</p>
  <div class="heroshot">{slot('ui-hero.jpg',
    'The MangaTCT workspace: a chapter typeset in English, with the seven '
    'steps across the top and the cleaning panel on the right',
    'The workspace on a finished chapter, the whole window', '16 / 10')}</div>
  <div class="stats">
    <span class="stat"><b>3</b><span>formats, end to end</span></span>
    <span class="stat"><b>7</b><span>steps, run in any order</span></span>
    <span class="stat"><b>4</b><span>languages out</span></span>
  </div>
</div></section>

{chapbar()}

<div class="chapters">
{chap_open("how")}
<section class="pan spn band" role="tabpanel" id="how" aria-labelledby="sb-how"><div class="wrap">
  <p class="kicker">Drag it</p>
  <h2 class="rise">A raw page in. A typeset page out.</h2>
  <p class="lead rise">One file, both ends of the pipeline. Pull the handle
  across.</p>
  <div class="rise" style="margin:30px 0 0">{ba}</div>
  <div class="balabels"><span>Drag any handle</span><span>Real pages from a real chapter</span></div>
  <div class="clips rise" style="margin-top:36px">
    <div class="clip">{slot('clip-stages.gif',
      'The three stages cycling: raw, cleaned, typeset',
      'A short loop of one page going raw to cleaned to typeset')}
      <h4>The three stages</h4>
      <p>Find and read, clean, typeset. Each stage is a step you can run, undo
      and run again on one page or the whole chapter.</p></div>
    <div class="clip">{slot('clip-fitter.gif',
      'One balloon typeset with four different lengths of English',
      'A loop of one balloon fitted with four lengths of English')}
      <h4>The fitter, working</h4>
      <p>Same balloon, four lengths of English. It changes the breaks and the
      size - the label on each frame is the size it chose - and never the words.</p></div>
    <div class="clip">{slot('clip-faces.gif',
      'The same balloon typeset in four different fonts',
      'A loop of one balloon in four different faces')}
      <h4>One block, four faces</h4>
      <p>A font is a decision about a block, not about a chapter. Change it on
      one bubble and nothing else moves.</p></div>
  </div>
</div></section>
<section class="pan spn band" role="tabpanel" id="steps" aria-labelledby="sb-steps"><div class="wrap">
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
    'A real chapter: six of the seven steps done on every page of it.',
    'The step bar with every step reading 23 of 23', '21 / 4')}</div>
</div></section>
<section class="pan spn band" role="tabpanel" id="screens" aria-labelledby="sb-screens"><div class="wrap">
  <p class="kicker">The screens</p>
  <h2 class="rise">Home, then four tabs - and you work in one of them.</h2>
  <div class="tabs rise" role="tablist" id="scrtabs" style="margin-top:24px">{screens}</div>
  <div class="rise">{screen_panels}</div>
</div></section>
</section>

{chap_open("formats")}
<section class="band" id="formats"><div class="wrap">
  <p class="kicker">Three formats, two jobs</p>
  <h2 class="rise">Manga, manhwa and manhua - what changes between them.</h2>
  <p class="lead rise" style="margin-bottom:30px">All three are supported end
  to end. Manga is a different job from the other two - a tool that pretends
  otherwise hands you a Korean chapter numbered backwards. Manhwa and manhua
  are the same job in two languages. Here is what actually differs.</p>
  <div class="tabs rise" role="tablist" id="fmttabs">{fmt_tabs}</div>
  <div class="rise" id="fmtpanels">{fmt_panels}</div>
  <p class="note" style="margin-top:30px">Everything AFTER the words is the
  same for all three: cleaning, fitting, typesetting, the effects and the
  export do not know which format they are working on, and that is deliberate.
  Out comes English, Spanish, Portuguese or French.</p>
</div></section>
</section>

{chap_open("control")}
<section class="pan spn band" role="tabpanel" id="control" aria-labelledby="sb-control"><div class="wrap">
  <p class="kicker">Editorial control</p>
  <h2 class="rise">The machine does the typing. You do the editing.</h2>
  <p class="lead rise">This is the part most tools skip. Everything the pipeline
  decided is a value you can see and change, on the page, without leaving the
  editor and without starting again.</p>
  <div style="margin-top:34px">{control}</div>
  <div class="rise" style="margin-top:38px">{shot('ui-workspace.jpg',
    'The whole workspace with one block selected and the typesetting panel open',
    'One block picked, and every control that applies to it.',
    'The workspace with a block selected and the typesetting rail open')}</div>
</div></section>
<section class="pan spn band" role="tabpanel" id="rules" aria-labelledby="sb-rules"><div class="wrap">
  <p class="kicker">What it will not do</p>
  <h2 class="rise">Six rules it will not break to make your life easier.</h2>
  <p class="lead rise">A tool that quietly edits your translation to make it fit
  is not saving you work - it is hiding work you now have to find.</p>
  <div class="grid g3 rise" style="margin-top:28px">{rules}</div>
  <div class="grid g2 rise" style="margin-top:30px">
    {shot('rule-font.jpg',
      'A finished page: every balloon set in one face, nothing borrowed',
      'Your font, and only your font. Every glyph on this page is the face '
      'that was picked for it - nothing borrowed from another family to '
      'fill a gap. A glyph the face cannot draw is kept and flagged, never '
      'quietly swapped.',
      'A finished panel in one face, from a real chapter', '5 / 3')}
    {shot('rule-spill.jpg',
      'Three SPLASH sound effects typeset across the top of a panel',
      'Sound effects sit on the artwork, not in a balloon. They are set at a '
      'size you can read and allowed to run across the panel - the way the '
      'original ink did, and the way a typesetter would draw it.',
      'A sound effect running across a panel, from a real chapter', '3 / 1')}
  </div>
</div></section>
</section>

{chap_open("models")}
<section class="pan spn band" role="tabpanel" id="models" aria-labelledby="sb-models"><div class="wrap">
  <p class="kicker">The models</p>
  <h2 class="rise">Pick the AI for each step. Or none.</h2>
  <div class="two tight rise" style="margin-top:28px">
    <div>
      <p>Reading, translating and proofreading each take their own AI company
      and their own model, so you can put a cheap fast one on the reading and a
      careful one on the words. <b>Claude, Google AI Studio (Gemini), or
      OpenAI, DeepSeek and Qwen through OpenRouter</b>. Every call goes through
      MangaTCT and is paid in TCT Coins, with no key to set up.</p>
      <p>Every step's run dialog shows its price in coins before you start,
      for the whole chapter and for the page on screen.</p>
    </div>
    <figure class="shot">{slot('ui-settings-models-real.jpg',
      'Per-step model settings',
      'Settings ▸ the model for each step, with the three services', '4 / 3')}</figure>
  </div>
  <h3 class="rise" style="margin-top:44px">What you can point them at</h3>
  <p class="lead rise">Eight of them, from about 12 coins to several hundred
  for a 23-page chapter, depending on the model. A hundred coins is a dollar,
  every one is priced per text box on what it really costs to run, and the
  calculator on the coins page tells you the number before you spend
  anything.</p>
  <div class="ais rise">{ais}</div>
</div></section>
<section class="pan spn band" role="tabpanel" id="credits" aria-labelledby="sb-credits"><div class="wrap">
  <p class="kicker">TCT Coins</p>
  <h2 class="rise">Free to try. Then you pay for what you actually run.</h2>
  <p class="lead rise">Make an account and verify your email, and it comes with
  100 free TCT Coins - enough to read and translate a chapter on a cheap Gemini
  model before you decide anything. After that you top up, and only the steps
  that call a model cost anything.</p>
  <div class="grid g3 rise" style="margin-top:28px">
    <div class="card"><h4>100 free coins</h4>
      <p class="mut">Once your email is verified. No card.</p></div>
    <div class="card"><h4>Pay as you go</h4>
      <p class="mut">Coins are spent by the steps that call a model: reading,
      translating, proofreading, and the hosted cleaner.</p></div>
    <div class="card"><h4>Always free</h4>
      <p class="mut">Finding text, typesetting and exporting. Read text can run
      on your computer for nothing, and manual translation skips the AI
      steps.</p></div>
  </div>
  <div class="cta" style="margin-top:28px">
    <a class="btn" href="signin.html">Create an account</a>
    <a class="btn ghost" href="download.html">Download the app</a>
    {contact_links()}
  </div>
</div></section>
</section>

{chap_open("compare")}
<section class="pan spn band" role="tabpanel" id="compare" aria-labelledby="sb-compare"><div class="wrap">
  <p class="kicker">Compared</p>
  <h2 class="rise">Against the two ways people do this now.</h2>
  <p class="lead rise">Doing it by hand gives you total control and costs you a
  day a chapter. A one-click translator gives you a chapter in a minute and no
  way to fix what it got wrong. This sits in the middle on purpose.</p>
  <div class="tblwrap rise" style="margin-top:28px"><table>
    <thead><tr><th></th><th>By hand in Photoshop</th>
      <th>One-click auto-translate</th><th class="me">MangaTCT (beta)</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <p class="note" style="margin-top:14px">The middle column describes the
  general class of one-click page translators, not any single product.</p>
</div></section>
<section class="pan spn band" role="tabpanel" id="faq" aria-labelledby="sb-faq"><div class="wrap">
  <p class="kicker">Questions</p>
  <h2 class="rise">The ones worth answering.</h2>
  <div class="rise" style="margin-top:22px">{faq}</div>
</div></section>
</section>

</div>

<footer><div class="wrap">
  <div class="foot">
    <div class="footabout">
      <a class="brand" href="#top">{mark(22)}<span class="wm"><b>Manga</b><i>TCT</i></span><em class="betapill">BETA</em></a>
      <p>Translate, clean and typeset manga, manhwa and manhua - and keep
      every decision the machine made where you can change it.</p>
    </div>
    <nav class="footlinks" aria-label="Product">
      <b>Product</b>
      <a href="download.html">Download</a>
      <a href="tutorial.html">Guide</a>
      <a href="fonts.html">Fonts</a>
      <a href="pricing.html">Coins</a>
      <a href="account.html">Account</a>
    </nav>
    <nav class="footlinks" aria-label="Help">
      <b>Help</b>
      {('<a href="' + SUPPORT["discord"] + '" target="_blank" rel="noopener">' + DISCORD_SVG + 'Discord</a>') if SUPPORT.get("discord") else ""}
      {('<a href="mailto:' + SUPPORT["email"] + '">' + MAIL_SVG + SUPPORT["email"] + '</a>') if SUPPORT.get("email") else ""}
      <a href="releases.html">All releases</a>
      <a href="{SOURCE}">Source (GPL-3.0)</a>
      <a href="license.html">License</a>
      <a href="privacy.html">Privacy</a>
    </nav>
  </div>
  <div class="footbar">
    <span>v{VERSION}{" " + CHANNEL if CHANNEL else ""}</span>
    <a class="built" href="https://lmbtechnology.com/" target="_blank" rel="noopener">
      <span>Built by</span>{lmb_mark()}<b>LMB Technology</b></a>
  </div>
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

  /* ---- the menus on the top bar. Hover or keyboard focus opens them with
     no script at all (the stylesheet); this adds click, Escape and click-away,
     which is what a phone, with no hover, needs. */
  var menus = [].slice.call(document.querySelectorAll('.menu'));
  function closeMenus(except){{
    menus.forEach(function(m){{
      if (m === except) return;
      m.classList.remove('open');
      var b = m.querySelector('.mbtn');
      if (b) b.setAttribute('aria-expanded', 'false');
    }});
  }}
  menus.forEach(function(m){{
    var b = m.querySelector('.mbtn');
    if (!b) return;
    b.addEventListener('click', function(e){{
      e.stopPropagation();
      var open = !m.classList.contains('open');
      closeMenus(m);
      m.classList.toggle('open', open);
      b.setAttribute('aria-expanded', open ? 'true' : 'false');
    }});
  }});
  document.addEventListener('click', function(){{ closeMenus(); }});
  document.addEventListener('keydown', function(e){{ if (e.key === 'Escape') closeMenus(); }});

  /* ---- tab strips: the chapters, their sub tabs, the formats and the
     screens. One handler for all of them - they behave identically, and a
     second copy of this is a second place for them to stop doing so. */
  var hdr = document.querySelector('header');
  function hh(){{ return hdr ? hdr.offsetHeight : 56; }}
  function setHH(){{ document.documentElement.style.setProperty('--hh', hh() + 'px'); }}
  setHH(); addEventListener('resize', setHH);

  function play(el, dir){{
    if (reduce || !el) return;
    el.style.setProperty('--dir', dir);
    el.classList.remove('enter'); void el.offsetWidth; el.classList.add('enter');
  }}
  function woke(el){{
    el.querySelectorAll('.rise').forEach(function(r){{ r.classList.add('in'); }});
    // The before/after handles measure their own width, and a panel that was
    // hidden measured nothing.
    dispatchEvent(new Event('resize'));
  }}
  function landOn(p){{
    // Switching while deep in a chapter lands at the top of the new one,
    // not somewhere in its middle.
    var bar = document.querySelector('.chapbar');
    if (!p || !bar) return;
    var top = p.getBoundingClientRect().top;
    if (top < hh() + bar.offsetHeight)
      scrollTo({{top: top + scrollY - hh() - bar.offsetHeight + 1,
                behavior: reduce ? 'auto' : 'smooth'}});
  }}
  function strip(id, lands){{
    var s = document.getElementById(id);
    if (!s) return null;
    var tabs = [].slice.call(s.querySelectorAll('[role=tab]'));
    var cur = Math.max(0, tabs.findIndex(function(t){{
      return t.getAttribute('aria-selected') === 'true'; }}));
    function show(i, quiet){{
      var dir = i >= cur ? 1 : -1;
      tabs.forEach(function(t, k){{
        var on = k === i;
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.tabIndex = on ? 0 : -1;
        var p = document.getElementById(t.getAttribute('aria-controls'));
        if (!p) return;
        p.hidden = !on;
        if (on) {{ woke(p); if (!quiet) {{ play(p, dir); if (lands) landOn(s.closest('.chap') || p); }} }}
      }});
      cur = i;
      if (tabs[i].scrollIntoView && !quiet)
        tabs[i].scrollIntoView({{block: 'nearest', inline: 'nearest'}});
    }}
    s.addEventListener('click', function(e){{
      var t = e.target.closest('[role=tab]');
      if (t) show(tabs.indexOf(t));
    }});
    s.addEventListener('keydown', function(e){{
      var i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      var n = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 :
              e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : -1;
      if (n < 0 || n >= tabs.length) return;
      e.preventDefault(); tabs[n].focus(); show(n);
    }});
    show(cur, true);
    return {{tabs: tabs, show: show, index: function(){{ return cur; }}}};
  }}
  var chap = strip('chaptabs', true);
  var subs = {{}};
  document.querySelectorAll('.subtabs').forEach(function(s){{ subs[s.id] = strip(s.id, true); }});
  strip('fmttabs'); strip('scrtabs');

  /* Every anchor on the page names a part of it. Open the chapter, and the
     sub tab, that part lives in - then go there. */
  function openFor(id, smooth){{
    var el = id && document.getElementById(id);
    var c = el && el.closest('.chap');
    if (!c || !chap) return false;
    var ci = chap.tabs.findIndex(function(t){{ return t.getAttribute('aria-controls') === c.id; }});
    if (ci >= 0 && ci !== chap.index()) chap.show(ci, true);
    var sp = el.closest('.spn');
    var st = sp && subs['subs-' + c.id.slice(2)];
    if (st) {{
      var si = st.tabs.findIndex(function(t){{ return t.getAttribute('aria-controls') === sp.id; }});
      if (si >= 0 && si !== st.index()) st.show(si, true);
    }}
    play(c, 1); woke(c);
    // `instant` and not `auto`: the page's own scroll-behavior is smooth, and
    // `auto` means whatever the page says - so arriving on a link animated a
    // long scroll instead of simply being there.
    el.scrollIntoView({{behavior: smooth && !reduce ? 'smooth' : 'instant', block: 'start'}});
    return true;
  }}
  document.addEventListener('click', function(e){{
    var a = e.target.closest('a[href^="#"]');
    if (!a) return;
    var id = a.getAttribute('href').slice(1);
    if (openFor(id, true)) {{ e.preventDefault(); history.pushState(null, '', '#' + id); closeMenus(); }}
  }});
  addEventListener('hashchange', function(){{ openFor(location.hash.slice(1), true); }});
  if (location.hash) openFor(location.hash.slice(1), false);
  // ...and again once the pictures are in. A picture that loads after the
  // jump pushes the section down, and somebody following a link to #rules
  // landed in the hero instead.
  addEventListener('load', function(){{ if (location.hash) openFor(location.hash.slice(1), false); }});

  /* ---- a press you can see: a ripple from where the pointer went down. */
  document.addEventListener('pointerdown', function(e){{
    var b = !reduce && e.target.closest('.btn,.tb,.navb,.ch,.sb');
    if (!b) return;
    var r = b.getBoundingClientRect(), d = Math.max(r.width, r.height) * 2.2;
    var i = document.createElement('i');
    i.className = 'rip';
    i.style.cssText = 'width:' + d + 'px;height:' + d + 'px;left:' +
      (e.clientX - r.left - d / 2) + 'px;top:' + (e.clientY - r.top - d / 2) + 'px';
    b.appendChild(i);
    setTimeout(function(){{ i.remove(); }}, 650);
  }});

  /* ---- a light that follows the pointer across a card. */
  if (!reduce) document.querySelectorAll('.ai,.step,.rule,.card,.clip').forEach(function(el){{
    el.classList.add('spot');
    el.addEventListener('pointermove', function(e){{
      var r = el.getBoundingClientRect();
      el.style.setProperty('--mx', (e.clientX - r.left) + 'px');
      el.style.setProperty('--my', (e.clientY - r.top) + 'px');
    }});
  }});

  /* ---- the numbers under the hero count up the first time they are seen. */
  if (!reduce && 'IntersectionObserver' in window) {{
    var co = new IntersectionObserver(function(es){{
      es.forEach(function(e){{
        if (!e.isIntersecting) return;
        co.unobserve(e.target);
        var el = e.target, to = parseInt(el.textContent, 10);
        if (!(to > 0)) return;
        var t0 = performance.now();
        (function tick(now){{
          var k = Math.min(1, (now - t0) / 900);
          el.textContent = String(Math.round(to * (1 - Math.pow(1 - k, 3))));
          if (k < 1) requestAnimationFrame(tick);
        }})(t0);
        setTimeout(function(){{ el.textContent = String(to); }}, 1400);
      }});
    }}, {{threshold: 0.6}});
    document.querySelectorAll('.stat b').forEach(function(s){{ co.observe(s); }});
  }}

  /* ---- how far down the page you are, along the top edge. */
  var prog = document.getElementById('progress');
  if (prog) {{
    var ticking = false;
    addEventListener('scroll', function(){{
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function(){{
        var h = document.documentElement.scrollHeight - innerHeight;
        prog.style.transform = 'scaleX(' + (h > 0 ? Math.min(1, scrollY / h) : 0) + ')';
        ticking = false;
      }});
    }}, {{passive: true}});
  }}

  /* ---- the hero picture leans a little toward the pointer. */
  var heroshot = document.querySelector('.heroshot'), hero = document.querySelector('.hero');
  if (heroshot && hero && !reduce && matchMedia('(pointer: fine)').matches) {{
    hero.addEventListener('pointermove', function(e){{
      var r = hero.getBoundingClientRect();
      var x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
      heroshot.style.transform = 'perspective(1600px) rotateX(' + (-y * 3).toFixed(2) +
        'deg) rotateY(' + (x * 4).toFixed(2) + 'deg)';
    }});
    hero.addEventListener('pointerleave', function(){{ heroshot.style.transform = ''; }});
  }}

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
  document.querySelectorAll('.ba').forEach(function(ba){{
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
  }});
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
