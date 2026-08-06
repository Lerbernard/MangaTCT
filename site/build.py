#!/usr/bin/env python3
"""Build the MangaTCT site.

Two outputs from one source: `index.html` beside `assets/` for hosting, and
`mangatct-site-standalone.html` with every picture and the font inlined, which
opens from a file:// URL with nothing beside it.

No icon set. Every picture on this page is a real screenshot of the editor or
a real page it produced — lee: *"d ont use teh icons you love to use so much"*.
"""
import base64
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(HERE, "assets")

MARK = open(f"{A}/mark.svg").read()
MARK_INNER = MARK.split(">", 1)[1].rsplit("</svg>", 1)[0]


def mark(size):
    return (f'<svg class="mk" viewBox="0 0 64 64" width="{size}" height="{size}" '
            f'aria-hidden="true">{MARK_INNER}</svg>')


def shot(src, alt, cap=None, cls=""):
    c = f'<figcaption>{cap}</figcaption>' if cap else ""
    return (f'<figure class="shot {cls}">'
            f'<img src="assets/{src}" alt="{alt}" loading="lazy">{c}</figure>')


STEPS = [
    ("1", "Find text", "Every block of writing on the page, boxed. "
     "comic-text-detector runs on your machine — no upload, no cost."),
    ("2", "Read text", "The Japanese, Korean or Chinese out of each box. "
     "Whole page in one request, or the page cut up for the small print."),
    ("3", "Translate", "Every box on the page in one go, with the synopsis, "
     "the character sheet and the glossary in front of it — so honorifics and "
     "names stay the same on page 39 as on page 1."),
    ("4", "Proofread", "A second pass that reads the page as a page: pronouns "
     "with no owner, a name one letter off the sheet, a line that does not "
     "answer the one before it. It writes a report you can read."),
    ("5", "Clean", "The Japanese comes off. Flat fill, tone copy, or the "
     "AI cleaner for the hard bits. Every bubble tells you which it used."),
    ("6", "Typeset", "The English goes in. Line breaks first, then size — "
     "never a hyphen, never a cut sentence, never a word split."),
    ("7", "Export", "The finished pages. Or the cleaned plates. Or a sheet "
     "with every box numbered, for someone else to typeset."),
]

TABS = [
    ("File", "Open a chapter, add pages, reorder them. One screen, one job."),
    ("Workspace", "The page. Boxes on the left of the split, typesetting on the "
     "right, every tool down the rail. This is where the work happens."),
    ("Results", "The proofread report and the chapter audit — what the second "
     "pass found, page by page, with the Japanese beside it."),
    ("Settings", "Fonts, box types, languages, models, cleaning. Per chapter, "
     "and remembered."),
]

RULES = [
    ("The whole translation goes in.",
     "Never reworded to fit, never trimmed, never split across two boxes. "
     "The fitter changes the line breaks and the size, and that is all it is "
     "allowed to change."),
    ("No hyphens.",
     "It will not break a word to make it fit. A dash the author typed — "
     "S-S-S-SORRY!! — is a different thing and survives exactly as written."),
    ("Your font, and only your font.",
     "It will not quietly swap a character for one your face happens to have, "
     "and it will not hand a line to a different family. If your font is short "
     "of a glyph, the box says so."),
    ("It never overwrites good work with nothing.",
     "If a re-run cannot typeset a bubble — a bad font, an empty mask — the "
     "typesetting already on the page stays. A blank bubble is never an answer."),
    ("A box you drew is yours.",
     "Draw a text box and it is independent: no detection behind it, not in "
     "the translation list, not counted as text to translate. Uploading a new "
     "translation does not sweep it away."),
    ("Nothing is uploaded that you did not send.",
     "Finding text and cleaning run locally. Reading and translating go to "
     "whichever model you point them at — including one on your own machine."),
]

CONTROL = [
    ("Every line, on the page",
     "The text list is the translation: one row per piece of Japanese, what it "
     "says and what it will say, and how sure the reader was. Open a row and "
     "the Japanese and the English are both fields \u2014 retype either. Change "
     "what kind of box it is, split it in two, or link it to the bubble it "
     "carries on into.",
     "ui-row-real.jpg"),
    ("Every block, letter by letter",
     "Font, size, rotation, curve, line gap, letter gap, caps. Text colour, "
     "outline colour, both as gradients. Shadow, outer glow, inner glow. Per "
     "block — not per page, not per chapter.",
     "ui-typesetting.jpg"),
    ("Every bubble, cleaned your way",
     "The page says which route cleaned each bubble — filled flat, tone "
     "copied, locally, by the AI — so you can see what it did before you trust "
     "it. Or drop in your own cleaned plate and skip the step.",
     "ui-clean.jpg"),
]

COMPARE = [
    ("Detection, OCR and translation", "by hand, box by box",
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
    ("Translate it entirely by hand", "yes", "no", "yes — a labelled file "
     "out, filled in, back"),
    ("Your own cleaned pages", "they are yours", "rarely", "drop them in"),
]

FAQ = [
    ("What do I need to run it?",
     "A machine with Python. The text detector is a single model file you "
     "download once and it runs on the processor — no graphics card needed. "
     "Reading and translating need an API key for whichever model you pick, "
     "or a local one; cleaning can run entirely offline."),
    ("Does it upload my raws?",
     "Finding text, cleaning, typesetting and exporting never leave your "
     "machine. Reading and translating send the page — or just the text — to "
     "the model you chose. Point them at something running on your own "
     "computer and nothing leaves at all."),
    ("Manhwa and manhua?",
     "Korean and Chinese are supported end to end, and reading direction is a "
     "setting. Long webtoon strips are the weak spot: the detector sees the "
     "whole page at one size, so very tall images need cutting up first."),
    ("Can I use it without any AI?",
     "Yes. Turn on manual translation and the three model steps go quiet. "
     "Download a labelled text file with every box numbered, fill it in, "
     "upload it back — or type straight into the page."),
    ("Is it finished?",
     "No. It typesets a chapter today and it is being worked on most days. "
     "The parts that have settled — finding text, reading it, translating, "
     "cleaning — are the parts that get left alone."),
]


def build():
    steps = "".join(
        f'<div class="step"><b>{n}</b><h4>{t}</h4><p>{d}</p></div>'
        for n, t, d in STEPS)
    tabs = "".join(f'<div class="tab"><h4>{t}</h4><p>{d}</p></div>'
                   for t, d in TABS)
    rules = "".join(f'<div class="rule"><h4>{t}</h4><p>{d}</p></div>'
                    for t, d in RULES)
    control = "".join(
        f'<div class="ctl"><div class="ctltx"><h3>{t}</h3><p>{d}</p></div>'
        f'<img src="assets/{img}" alt="{t}" loading="lazy"></div>'
        for t, d, img in CONTROL)
    rows = "".join(
        f'<tr><th>{a}</th><td>{b}</td><td>{c}</td><td class="me">{d}</td></tr>'
        for a, b, c, d in COMPARE)
    faq = "".join(f'<details><summary>{q}</summary><p>{a}</p></details>'
                  for q, a in FAQ)

    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MangaTCT — translate, clean, typeset</title>
<meta name="description" content="A manga, manhwa and manhua translation
 editor. Finds the text, reads it, translates it, cleans the page and typesets
 it — and hands you every one of those decisions.">
<link rel="icon" href="assets/mark.svg" type="image/svg+xml">
<style>
@font-face{{font-family:AntonLocal;src:url(assets/anton.ttf) format('truetype');
 font-display:swap}}
:root{{--bg:#0d0f14;--panel:#141821;--panel2:#1a1f29;--line:#252c38;
 --fg:#eceef3;--dim:#8b93a4;--accent:#ffc400;--accent2:#ff9d00;--ok:#4ade80}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{margin:0;background:var(--bg);color:var(--fg);
 font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
 -webkit-font-smoothing:antialiased}}
img{{max-width:100%;display:block}}
a{{color:var(--accent)}}
.wrap{{max-width:1120px;margin:0 auto;padding:0 24px}}
h1,h2,h3,h4,.brand b,.brand i{{font-family:AntonLocal,Impact,"Arial Narrow Bold",sans-serif;
 font-weight:400;letter-spacing:.01em;line-height:1.06}}
h2{{font-size:clamp(30px,4.4vw,46px);margin:0 0 10px}}
h3{{font-size:22px;margin:0 0 6px}}
h4{{font-size:19px;margin:0 0 5px}}
p{{margin:0 0 14px}}
.lead{{color:var(--dim);font-size:18px;max-width:62ch}}
section{{padding:76px 0;border-top:1px solid var(--line)}}
.kicker{{font-size:12px;letter-spacing:.2em;text-transform:uppercase;
 color:var(--accent);margin:0 0 12px;font-weight:600}}

/* header */
header{{position:sticky;top:0;z-index:50;background:rgba(13,15,20,.86);
 backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}}
.hd{{display:flex;align-items:center;gap:26px;height:62px}}
.brand{{display:flex;align-items:flex-end;gap:9px;text-decoration:none;color:inherit}}
.brand svg{{display:block}}
/* MangaTCT is one word. `gap` on a flex row falls between EVERY child, so the
   space meant to sit between the mark and the name was also splitting the
   name in half. */
.brand .wm{{display:flex;align-items:flex-end;gap:0}}
.brand b{{font-size:25px;line-height:.82}}
.brand i{{font-size:25px;line-height:.82;color:var(--accent);font-style:normal}}
.hd nav{{margin-left:auto;display:flex;gap:22px;font-size:14px}}
.hd nav a{{color:var(--dim);text-decoration:none}}
.hd nav a:hover{{color:var(--fg)}}
.btn{{display:inline-block;background:var(--accent);color:#141821;
 padding:11px 20px;border-radius:8px;font-weight:700;text-decoration:none;
 font-size:15px;border:1px solid var(--accent)}}
.btn:hover{{background:#ffd851}}
.btn.ghost{{background:transparent;color:var(--fg);border-color:var(--line)}}
.btn.ghost:hover{{background:var(--panel2)}}

/* hero */
.hero{{padding:78px 0 10px;border:0}}
.hero h1{{font-size:clamp(40px,5.6vw,72px);margin:0 0 16px;max-width:19ch}}
.hero h1 em{{color:var(--accent);font-style:normal}}
.hero .lead{{font-size:20px;max-width:58ch}}
.cta{{display:flex;gap:12px;flex-wrap:wrap;margin:26px 0 8px;align-items:center}}
.note{{color:var(--dim);font-size:13px}}
.heroshot{{margin-top:44px;border:1px solid var(--line);border-radius:14px;
 overflow:hidden;background:var(--panel);box-shadow:0 30px 90px rgba(0,0,0,.55)}}
.bandmark{{display:flex;gap:34px;flex-wrap:wrap;color:var(--dim);font-size:14px;
 margin-top:22px}}
.bandmark b{{color:var(--fg);font-family:AntonLocal,sans-serif;font-size:17px;
 letter-spacing:.02em}}

/* generic blocks */
.grid{{display:grid;gap:18px}}
.g3{{grid-template-columns:repeat(3,1fr)}}
.g2{{grid-template-columns:repeat(2,1fr)}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;
 padding:20px}}
.step{{background:var(--panel);border:1px solid var(--line);border-radius:12px;
 padding:18px 20px;position:relative}}
.step b{{position:absolute;top:14px;right:16px;font-family:AntonLocal,sans-serif;
 font-size:34px;color:#20262f}}
.step p{{color:var(--dim);font-size:14.5px;margin:0}}
.tab p{{color:var(--dim);font-size:14.5px;margin:0}}
.rule h4{{color:var(--accent)}}
.rule p{{color:var(--dim);font-size:14.5px;margin:0}}
figure.shot{{margin:0}}
figure.shot img{{border:1px solid var(--line);border-radius:12px;background:var(--panel)}}
figcaption{{color:var(--dim);font-size:13px;margin-top:9px}}

/* control rows */
.ctl{{display:grid;grid-template-columns:1fr 380px;gap:34px;align-items:center;
 padding:26px 0;border-top:1px solid var(--line)}}
.ctl:first-child{{border-top:0}}
.ctl img{{border:1px solid var(--line);border-radius:12px;max-height:420px;
 object-fit:cover;object-position:top}}
.ctl p{{color:var(--dim);margin:0}}

/* clips */
.clips{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}
.clip{{background:var(--panel);border:1px solid var(--line);border-radius:12px;
 padding:14px}}
.clip img{{border-radius:8px;width:100%}}
.clip h4{{margin:12px 0 4px;font-size:17px}}
.clip p{{color:var(--dim);font-size:14px;margin:0}}

/* table */
table{{width:100%;border-collapse:collapse;font-size:14.5px}}
th,td{{text-align:left;padding:13px 14px;border-top:1px solid var(--line);
 vertical-align:top}}
thead th{{color:var(--dim);font-size:12px;letter-spacing:.14em;
 text-transform:uppercase;border-top:0;font-weight:600;font-family:inherit}}
tbody th{{font-weight:600;color:var(--fg);width:34%;font-family:inherit}}
td{{color:var(--dim)}}
td.me{{color:var(--fg)}}
thead th.me{{color:var(--accent)}}

/* credits */
.credits{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}
.credits .card b{{display:block;font-family:AntonLocal,sans-serif;font-size:26px;
 margin-bottom:4px}}
.credits .card p{{color:var(--dim);font-size:14.5px;margin:0}}

details{{border-top:1px solid var(--line);padding:16px 0}}
summary{{cursor:pointer;font-weight:600;font-size:17px}}
details p{{color:var(--dim);margin:10px 0 0;max-width:76ch}}

footer{{border-top:1px solid var(--line);padding:40px 0 60px;color:var(--dim);
 font-size:14px}}
.foot{{display:flex;gap:20px;flex-wrap:wrap;align-items:center}}
.foot .brand b,.foot .brand i{{font-size:20px}}
.todo{{background:#241f08;border:1px dashed #6b5a12;color:#e8d48a;
 padding:2px 7px;border-radius:5px;font-size:12px}}
@media(max-width:900px){{
 .g3,.g2,.clips,.credits{{grid-template-columns:1fr}}
 .ctl{{grid-template-columns:1fr}}
 .hd nav{{display:none}}
}}
</style>

<header><div class="wrap hd">
  <a class="brand" href="#top">{mark(28)}<span class="wm"><b>Manga</b><i>TCT</i></span></a>
  <nav>
    <a href="#how">How it works</a>
    <a href="#control">Control</a>
    <a href="#rules">Rules</a>
    <a href="#compare">Compare</a>
    <a href="#credits">Credits</a>
    <a href="pricing.html">Pricing</a>
    <a href="account.html">Account</a>
  </nav>
  <a class="btn" href="signin.html">Sign in</a>
</div></header>

<a id="top"></a>
<section class="hero"><div class="wrap">
  <p class="kicker">Manga · manhwa · manhua</p>
  <h1>Translate, clean and typeset a chapter <em>without giving up the page</em></h1>
  <p class="lead">MangaTCT finds every block of text, reads it, translates it
  with your glossary and your character sheet, wipes the original off the art
  and sets the English back into the balloon. Then it hands you all of it:
  every line, every block, every bubble, down to the outline colour.</p>
  <div class="cta">
    <a class="btn" href="#credits">Start free — you get credits to try it</a>
    <a class="btn ghost" href="#how">See it work</a>
  </div>
  <p class="note">Free credits on signup, no card. Finding text, cleaning and
  typesetting run on your own machine and cost nothing.</p>
  <div class="heroshot"><img src="assets/ui-hero-real.jpg"
    alt="The MangaTCT workspace: a 23-page chapter typeset in English, with
         the seven steps across the top and the cleaning panel on the right"></div>
  <div class="bandmark">
    <span><b>23</b> pages a chapter, in one pass</span>
    <span><b>7</b> steps, run in any order</span>
    <span><b>0</b> hyphens, ever</span>
  </div>
</div></section>

<section id="how"><div class="wrap">
  <p class="kicker">What it does</p>
  <h2>A raw page in. A typeset page out.</h2>
  <p class="lead">Every picture below is a real page this chapter went through
  — the same file, at three points in the pipeline. Nothing here is a mock-up.</p>
  <div style="margin:30px 0">{shot('triptych.jpg',
    'A manga page shown three times: raw with Japanese, cleaned with empty '
    'balloons, and typeset in English')}</div>
  <div class="clips">
    <div class="clip"><img src="assets/clip-pipeline.gif" alt="The three stages
      cycling: raw, cleaned, typeset" loading="lazy">
      <h4>The three stages</h4>
      <p>Find and read, clean, letter. Each stage is a step you can run, undo
      and run again on one page or the whole chapter.</p></div>
    <div class="clip"><img src="assets/clip-fit.gif" alt="One balloon typeset
      with four different lengths of English at four different sizes" loading="lazy">
      <h4>The fitter, working</h4>
      <p>Same balloon, four lengths of English. It changes the breaks and the
      size — 34pt down to 16pt — and never the words.</p></div>
    <div class="clip"><img src="assets/clip-font.gif" alt="The same balloon
      typeset in four different fonts" loading="lazy">
      <h4>One block, four faces</h4>
      <p>A font is a decision about a block, not about a chapter. Change it on
      one bubble and nothing else moves.</p></div>
  </div>
</div></section>

<section><div class="wrap">
  <p class="kicker">The steps</p>
  <h2>Seven of them, in three groups.</h2>
  <p class="lead">Translation, image, export. The bar says where the chapter is
  — a count on every button and a fill under it. It does not decide what you
  are allowed to press: run any step, in any order, on any pages you like.</p>
  <div style="margin:28px 0">{shot('ui-steps-real.jpg',
    'The seven-step bar on a finished chapter: Find text, Read text, '
    'Translate, Proofread, Clean and Typeset all reading 23 of 23',
    'A real chapter, six steps done, twenty-three pages each.')}</div>
  <div class="grid g3" style="margin-top:22px">{steps}</div>
  <div class="grid g2" style="margin-top:30px;align-items:start">
    {shot('ui-export-real.jpg',
      'The export dialog, with the three things it can write',
      'Export writes what you ask for: the finished pages, the cleaned plates '
      'with the Japanese gone and no English on them, or the original art with '
      'every box drawn and numbered for someone else to typeset.')}
    {shot('ui-toolbox-real.jpg',
      'The tool rail, with a slot opened to show the tools inside it',
      'The tool rail is Photoshop-shaped: a slot per job, and the rest of the '
      'tools in it one right-click away.')}
  </div>
</div></section>

<section><div class="wrap">
  <p class="kicker">The screens</p>
  <h2>Four tabs, and only one of them is ever in your way.</h2>
  <div class="grid g2" style="margin-top:26px">
    <div>{"".join(f'<div class="card tab" style="margin-bottom:14px"><h4>{t}</h4><p>{d}</p></div>' for t, d in TABS)}</div>
    <div>{shot('ui-translation-real.jpg',
      'The Translation view: numbered boxes over the raw page, and every line '
      'of it listed down the right with the Japanese under the English')}</div>
  </div>
</div></section>

<section id="control"><div class="wrap">
  <p class="kicker">Editorial control</p>
  <h2>The machine does the typing. You do the editing.</h2>
  <p class="lead">This is the part most tools skip. Everything the pipeline
  decided is a value you can see and change, on the page, without leaving the
  editor and without starting again.</p>
  <div style="margin-top:26px">{control}</div>
  <div style="margin-top:34px">{shot('ui-typesetting-full.jpg',
    'The whole workspace with one block selected and the typesetting panel open',
    'One block picked, and every control that applies to it.')}</div>
</div></section>

<section id="rules"><div class="wrap">
  <p class="kicker">What it will not do</p>
  <h2>Six rules it will not break to make your life easier.</h2>
  <p class="lead">A tool that quietly edits your translation to make it fit is
  not saving you work — it is hiding work you now have to find.</p>
  <div class="grid g3" style="margin-top:26px">{rules}</div>
  <div class="grid g2" style="margin-top:30px">
    {shot('cmp-substitutes.jpg',
      'The same page typeset twice: with glyph substitution off, the music '
      'note is kept and the box is flagged; with it on, the note is removed',
      'Your font, and only your font. Left: the switch off — the character '
      'your face cannot draw is KEPT and the box is flagged by name. Right: '
      'the switch on, if you want it.')}
    {shot('cmp-spill.jpg',
      'Outside text and a sound effect typeset at 8pt inside their box, and '
      'again at 12pt spilling out of it',
      'Outside text and sound effects sit on artwork, not on paper. Rather '
      'than shrink under the legible minimum they are set at it and allowed '
      'to run past the box — the way a typesetter would.')}
  </div>
</div></section>

<section><div class="wrap">
  <p class="kicker">The models</p>
  <h2>Bring your own AI. Or none.</h2>
  <div class="grid g2" style="margin-top:26px;align-items:center">
    <div>
      <p>Reading, translating and proofreading each take their own provider and
      their own model, so you can put a cheap fast one on the reading and a
      careful one on the words. Claude, Gemini, OpenAI, OpenRouter, or something
      running on your own machine.</p>
      <p>No key? Download the exact request the translator would have sent,
      paste it into whatever you already pay for, and drop the answer back in.</p>
      <p><b>Or do it entirely by hand.</b> Turn on manual translation and the
      three model steps go quiet. You get a labelled text file with every box
      numbered the way the box sheet numbers it, the Japanese beside each one
      and room to type underneath. Fill in as much as you like, upload it back,
      and whatever is in it wins.</p>
    </div>
    {shot('ui-settings-models.jpg', 'Per-step model settings')}
  </div>
  <div style="margin-top:26px">{shot('ui-settings-fonts-real.jpg',
    'Settings: fonts and typesetting, with a face per box type',
    'Fonts you upload stay with YOU, not with the chapter — the next project '
    'already has them. Every box type gets its own face, and you can add your '
    'own types: caption box, thought bubble, burst, whisper, aside, sign.')}</div>
</div></section>

<section id="compare"><div class="wrap">
  <p class="kicker">Compared</p>
  <h2>Against the two ways people do this now.</h2>
  <p class="lead">Doing it by hand gives you total control and costs you a day
  a chapter. A one-click translator gives you a chapter in a minute and no way
  to fix what it got wrong. This sits in the middle on purpose.</p>
  <table style="margin-top:26px">
    <thead><tr><th></th><th>By hand in Photoshop</th>
      <th>One-click auto-translate</th><th class="me">MangaTCT</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p class="note" style="margin-top:14px">The middle column describes the
  general class of one-click page translators, not any single product.</p>
</div></section>

<section id="credits"><div class="wrap">
  <p class="kicker">Credits</p>
  <h2>Free to try. Then you pay for what you actually run.</h2>
  <p class="lead">Make an account and it comes with credits — enough to take a
  chapter through end to end before you decide anything. After that you top up,
  and only the steps that call a model cost anything.</p>
  <div class="credits" style="margin-top:26px">
    <div class="card"><b>Free credits</b>
      <p>On signup. No card. Run a real chapter, not a demo page.</p></div>
    <div class="card"><b>Pay as you go</b>
      <p>Credits are spent by the steps that call a model — reading,
      translating, proofreading, and AI cleaning if you turn it on.</p></div>
    <div class="card"><b>Free forever, if you want</b>
      <p>Point the steps at your own key or your own local model and it costs
      you nothing here. Finding text, cleaning and typesetting never cost
      credits.</p></div>
  </div>
  <div class="cta" style="margin-top:26px">
    <a class="btn" href="#" data-fill="signup">Create an account</a>
    <a class="btn ghost" href="#" data-fill="contact">Talk to us</a>
    <span class="todo">both links need a URL</span>
  </div>
</div></section>

<section><div class="wrap">
  <p class="kicker">Questions</p>
  <h2>The ones worth answering.</h2>
  <div style="margin-top:20px">{faq}</div>
</div></section>

<footer><div class="wrap foot">
  <a class="brand" href="#top">{mark(22)}<span class="wm"><b>Manga</b><i>TCT</i></span></a>
  <span>Translate · clean · typeset.</span>
  <span style="margin-left:auto"><span class="todo">footer links go here</span></span>
</div></footer>
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
        if f.endswith((".jpg", ".gif", ".svg")):
            mime = {"jpg": "image/jpeg", "gif": "image/gif",
                    "svg": "image/svg+xml"}[f.rsplit(".", 1)[1]]
            html = html.replace(f"assets/{f}", data(f"{A}/{f}", mime))
    return html


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
