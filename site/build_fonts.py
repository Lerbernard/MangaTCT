#!/usr/bin/env python3
"""Build `site/fonts.html` - the recommended faces, as a page of the website.

lee: *"move teh fonts tab into the front end website not the app"*.

It was a tab in the editor. He is right that it does not belong there, and the
reason is what the page IS: everything else in the editor acts on the chapter
you have open, and this acts on nothing. It is a thing you read once, before
you start, and then again when a series needs a different voice - which is a
page of the website, next to the guide and the pricing, where somebody can
find it without a project loaded and can send the link to whoever they work
with.

## Generated, not written

From `fontpicks.PICKS`, the same table the editor reads. The alternative was a
hand-written page, and a hand-written page is a second copy of a list that
changes - it would have been right on the day it was written and quietly wrong
by the third time somebody added a recommendation.

## The specimens are real, and this is the one place they can all be

The editor's version could only draw a face it had a FILE for, so half the
rows were a name in the UI font. Here every Google Fonts family is a webfont
away, so each row is set in the face it names - which is the whole of what a
recommendation page is for. The two that are not on Google Fonts cannot be,
and their rows say why rather than pretending: Anime Ace may not be
redistributed and Wild Words costs money, which is the same fact that keeps
both out of the app's own folder.

Run: `python3 site/build_fonts.py`
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from mangatl import fontpicks as FP                      # noqa: E402
from mangatl import kinds as K                           # noqa: E402

FONTS_DIR = os.path.join(os.path.dirname(HERE), "fonts")


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def bundled_families():
    """The families that ship inside MangaTCT, read off the folder.

    A static fact about the download, and the useful one on a public page -
    the site cannot know what somebody has installed, and "you already have
    this" is a promise only the app can make.
    """
    out = set()
    for f in os.listdir(FONTS_DIR):
        if f.lower().endswith((".ttf", ".otf")):
            out.add(os.path.splitext(f)[0].split("-")[0]
                    .replace(" ", "").lower())
    return out


def family_slug(family):
    return family.replace(" ", "").lower()


MARK = ('<svg class="mk" viewBox="0 0 64 64" width="26" height="26" '
        'aria-hidden="true"><defs><linearGradient id="ag" x1="0" y1="0" '
        'x2=".25" y2="1"><stop offset="0" stop-color="#ffc400"/>'
        '<stop offset="1" stop-color="#ff9d00"/></linearGradient></defs>'
        '<path d="M7 10 L18 10 L32 30 L46 10 L57 10 L57 46 L46.5 46 '
        'L46.5 26.5 L35.5 42 L28.5 42 L17.5 26.5 L17.5 47 L11.5 60 L7 47 Z" '
        'fill="url(#ag)"/></svg>')

# The word every specimen is set in. A shout, because it is the one line that
# reads differently in every one of these faces - "Sample" tells you almost
# nothing about a display face.
SPECIMEN = "R- Really?!"

FAMILY_LABELS = {"bubble": "Bubble text", "freefloat": "Freefloat text",
                 "sfx": "Sound effect"}
DEFAULT_LABELS = {"bubble": "Regular speech", "freefloat": "Freefloat text",
                  "sfx": "Sound effect"}


def rows_for(kind):
    return FP.PICKS.get(kind) or []


def google_families():
    """Every Google Fonts family on the page, for the one stylesheet link.

    One request with every family on it rather than one per row: the browser
    asks for the whole page's type in a single round trip, which is what
    Google Fonts' `family=` repeated parameter is for.
    """
    out = []
    for picks in FP.PICKS.values():
        for p in picks:
            if p.source == FP.GOOGLE and p.family not in out:
                out.append(p.family)
    return sorted(out)


def build():
    have = bundled_families()
    fams = google_families()
    link = ("https://fonts.googleapis.com/css2?"
            + "&".join("family=" + f.replace(" ", "+") for f in fams)
            + "&display=swap")

    blocks = []
    for fam in K.FAMILIES:
        kinds = [(fam, DEFAULT_LABELS[fam])] + [
            (k, lb) for k, lb in K.PRELOADED.get(fam, ())]
        inner = []
        for kind, label in kinds:
            picks = rows_for(kind)
            if not picks:
                continue
            cards = []
            for p in picks:
                slug = family_slug(p.family)
                is_here = slug in have
                if p.source == FP.GOOGLE:
                    spec = ('<p class="spec" style="font-family:\'%s\',cursive">'
                            "%s</p>" % (esc(p.family), esc(SPECIMEN)))
                else:
                    # Not on Google Fonts, so there is no webfont to set it in.
                    # Saying so is better than setting it in the body face and
                    # letting the row look like a specimen that failed.
                    spec = ('<p class="spec none">Not on Google Fonts — see '
                            "the link for a specimen.</p>")
                chip = ('<span class="fchip in">Ships with MangaTCT</span>'
                        if is_here else
                        '<a class="fchip get" href="%s" target="_blank" '
                        'rel="noopener noreferrer">Get it from %s</a>'
                        % (esc(p.url), esc(p.source)))
                price = ('<span class="fprice">%s</span>' % esc(p.price)
                         if p.price else "")
                cards.append(
                    '<article class="fcard">'
                    '<header><h4>%s</h4>%s</header>'
                    "%s"
                    '<p class="fwhy">%s</p>'
                    '<p class="flic">%s %s</p>'
                    "</article>"
                    % (esc(p.family), chip, spec, esc(p.why),
                       esc(p.licence), price))
            inner.append('<section class="fkind"><h3>%s</h3>'
                         '<div class="fgrid">%s</div></section>'
                         % (esc(label), "".join(cards)))
        blocks.append('<section class="ffam"><h2>%s</h2>%s</section>'
                      % (esc(FAMILY_LABELS[fam]), "".join(inner)))

    sources = "".join(
        '<li><a href="%s" target="_blank" rel="noopener noreferrer">%s</a> — %s</li>'
        % (esc(FP.SOURCES[s]["home"]), esc(s), esc(FP.SOURCES[s]["how"]))
        for s in FP.SOURCES)

    html = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Fonts | MangaTCT</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Faces worth using for each kind of box in a
comic - what each one is for, where to download it, and what its licence lets
you do.">
<link rel="icon" href="assets/mark.svg" type="image/svg+xml">
<link rel="stylesheet" href="style.css">
<script>try{var d=document.documentElement,t=localStorage.getItem('tct-theme');
if(t)d.dataset.theme=t}catch(e){}</script>
<!-- Every family on the page, in one request. The specimens are the point of
     the page, so they are worth a stylesheet; `display=swap` means a slow
     answer shows the body face rather than nothing. -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="__LINK__">

<style>
.ffam{margin:34px 0 0}
.ffam>h2{font-size:13px;letter-spacing:.1em;text-transform:uppercase;
 color:var(--mut);margin:0 0 4px;font-weight:700}
.fkind{margin:18px 0 0}
.fkind>h3{font-size:19px;margin:0 0 10px}
.fgrid{display:grid;gap:12px;
 grid-template-columns:repeat(auto-fit,minmax(268px,1fr))}
.fcard{border:1px solid var(--line);border-radius:14px;background:var(--panel);
 padding:14px 16px}
.fcard header{display:flex;align-items:center;justify-content:space-between;
 gap:10px;margin:0 0 8px}
.fcard h4{margin:0;font-size:15.5px}
/* The specimen. Big, because it is what the row is FOR - a name tells you
   nothing about a face and this page exists to show you. */
.spec{margin:0 0 10px;font-size:30px;line-height:1.25;color:var(--ink);
 overflow-wrap:anywhere}
.spec.none{font-size:13px;color:var(--mut);font-style:italic;line-height:1.5}
.fwhy{margin:0 0 8px;font-size:14px;color:var(--dim);line-height:1.5}
.flic{margin:0;font-size:12px;color:var(--mut)}
.fprice{color:var(--ink);font-weight:700}
.fchip{font-size:10.5px;font-weight:800;letter-spacing:.05em;
 text-transform:uppercase;padding:4px 10px;border-radius:999px;
 border:1px solid currentColor;white-space:nowrap;flex:0 0 auto;
 text-decoration:none}
.fchip.in{color:var(--good)}
.fchip.get{color:var(--accent)}
.fchip.get:hover{color:var(--accent2)}
.srcs{margin:12px 0 0;padding:0 0 0 18px;color:var(--dim);font-size:14px;
 line-height:1.6}
.srcs li{margin:0 0 4px}
</style>

<header>
  <a class="brand" href="index.html">__MARK__<span class="wm"><b>Manga</b><i>TCT</i></span></a>
  <nav>
    <a class="navb" href="index.html">Home</a>
    <a class="navb" href="tutorial.html">Guide</a>
    <a class="navb on" href="fonts.html">Fonts</a>
    <a class="navb" href="pricing.html">Coins</a>
    <a class="navb cta" id="acct" href="account.html">Account</a>
    <button class="navb icon" id="theme" type="button" aria-label="Theme"></button>
  </nav>
</header>

<main>
  <h1>Fonts for comic typesetting</h1>
  <p class="lede">Choosing a face is the one part of typesetting MangaTCT
    cannot do for you, and it is the part that decides what the finished page
    looks like. Here is what to use for each kind of box, why, and where to
    get it. Every row below is set in the face it names.</p>

  <div class="note">
    <b>Eleven of these ship inside MangaTCT</b> and need no download. The rest
    are one click away. The reason the app carries some and links the others
    is licensing, not taste: a program you download may only carry a font
    whose licence permits redistribution, and two of the faces this craft is
    actually set in do not.
  </div>

  <h2 style="margin-top:26px">Where they come from</h2>
  <ul class="srcs">__SOURCES__</ul>

__BLOCKS__

  <div class="note" style="margin-top:34px">
    <b>Adding one to MangaTCT.</b> Install it the normal way for your
    computer, or drop the file straight into the app: <b>Settings → Fonts →
    Add fonts…</b>. Either way it appears in the picker on every box type.
  </div>
</main>

<footer>
  <div class="wrap">
    <a class="brand" href="index.html">__MARK__<span class="wm"><b>Manga</b><i>TCT</i></span></a>
    <nav>
      <a href="index.html">Home</a>
      <a href="tutorial.html">Guide</a>
      <a href="fonts.html">Fonts</a>
      <a href="pricing.html">Coins</a>
    </nav>
  </div>
</footer>

<script>
(function(){
  var d = document.documentElement, b = document.getElementById('theme');
  function paint(){ b.textContent = d.dataset.theme !== 'light' ? '\\u263c' : '\\u263e'; }
  b.addEventListener('click', function(){
    var next = (d.dataset.theme !== 'light') ? 'light' : 'dark';
    d.dataset.theme = next;
    try{ localStorage.setItem('tct-theme', next); }catch(e){}
    paint();
  });
  paint();
})();
</script>
</html>
"""
    html = (html.replace("__LINK__", link)
                .replace("__MARK__", MARK)
                .replace("__SOURCES__", sources)
                .replace("__BLOCKS__", "\n".join(blocks)))
    out = os.path.join(HERE, "fonts.html")
    open(out, "w", encoding="utf-8").write(html)
    n = sum(len(v) for v in FP.PICKS.values())
    print("wrote %s - %d faces over %d box types, %d families webfonted"
          % (out, n, len(FP.PICKS), len(fams)))


if __name__ == "__main__":
    build()
