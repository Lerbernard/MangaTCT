# -*- coding: utf-8 -*-
"""Faces worth using for each box type, and where to get the ones we cannot ship.

lee: *"i want you to vcreate a pge inteh webisyte witha bunch of reciomended
fonts fro each box type and subtype anbd a link to doenload them from a
trusted website for tehe ones that rae not on the app"*.

## Why this is a table and not a paragraph

Choosing a face is the one part of typesetting this app cannot do for you, and
it is the part that decides what the finished page looks like. The app ships
eleven families - every one of them OFL, because that is the only licence that
lets a downloaded program carry a font at all (`fonts/LICENSES.md` has the
whole argument) - and the faces most of this craft is actually set in are not
among them, for exactly that reason.

So the table has to say three things about every entry and never blur them:

* **what it is for**, in one sentence about the TYPE and not about the font;
* **where it comes from**, named, so the download is a decision and not a
  click on whatever a search engine put first;
* **what its licence permits**, because "free to download" and "free to use in
  work you sell" and "free to redistribute" are three different permissions
  and the difference is the whole reason six of these are links rather than
  files.

## The three sources, and why only three

**Google Fonts** for everything that can be. OFL or Apache, downloadable as a
zip from the family's own page, no account, no bundler, and the same licence
the app's own folder is built on - so anything from here can also be dropped
into a project's `fonts/` folder and shared with whoever you work with.

**Blambot** for Anime Ace. It is the face most of scanlation is set in, it is
free for comic work including work that earns money, and Blambot's terms
forbid redistribution under every free tier - which is why it left this app's
folder on 2026-08-26 and why it is a link here. Download it from Blambot
directly; the aggregator sites that carry it are carrying it without the
licence attached.

**Comicraft** for Wild Words, which is the standard dialogue face in English
manga publishing and is a paid font. It is here because leaving the actual
industry answer off a page about recommended faces would be a kind of lie, and
its price is on the row so nobody clicks it expecting a free download.

Nothing else. A recommendation list is a promise that somebody checked, and
three sources is the number that can be checked.

## The shape

`PICKS[kind]` is a list, best-first. Every entry names a FAMILY - never a file
- because the file is what the app's own folder deals in and a family is what a
person downloads.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Dict, List

# ---------------------------------------------------------------- sources
#
# Named once. A link is a promise about where a file comes from, and a URL
# written out at each of forty use sites is forty chances to promise something
# else.

GOOGLE = "Google Fonts"
BLAMBOT = "Blambot"
COMICRAFT = "Comicraft"

SOURCES = {
    GOOGLE: {
        "home": "https://fonts.google.com/",
        # "Get font" on a family's own page downloads the whole family as a
        # zip. No account, no installer, no bundler.
        "how": "Open the family's page and press Get font — it downloads a "
               "zip of the whole family.",
    },
    BLAMBOT: {
        "home": "https://blambot.com/",
        "how": "Free for comic work, including work you sell. Download it "
               "from Blambot itself: the aggregator sites that carry these "
               "carry them without the licence attached.",
    },
    COMICRAFT: {
        "home": "https://comicraft.com/",
        "how": "A paid font, bought per style. Listed because it is what "
               "English manga publishing actually uses, not because it is "
               "free.",
    },
}


def google(family: str) -> str:
    """A family's own page on Google Fonts, from its name."""
    return "https://fonts.google.com/specimen/" + family.replace(" ", "+")


@dataclass(frozen=True)
class Pick:
    family: str          # what a person downloads and what the picker lists
    why: str             # one sentence about the TYPE, not about the font
    source: str          # one of the three above
    licence: str
    url: str
    price: str = ""      # said out loud when it is not free

    def as_dict(self) -> dict:
        return asdict(self)


def _g(family: str, why: str, licence: str = "OFL 1.1") -> Pick:
    return Pick(family=family, why=why, source=GOOGLE, licence=licence,
                url=google(family))


# Two that are not on Google Fonts and are named on more than one row.
ANIME_ACE = Pick(
    family="Anime Ace",
    why="What most of scanlation is set in (the current cut is Anime Ace "
        "2.0) — an even, slightly condensed hand that stays legible small "
        "and has a real italic.",
    source=BLAMBOT, licence="Free for comic work; may not be redistributed",
    url="https://blambot.com/collections/all-fonts")

WILD_WORDS = Pick(
    family="Wild Words",
    why="The standard dialogue face in English manga publishing — wider and "
        "warmer than Anime Ace, with a matching italic and small caps.",
    source=COMICRAFT, licence="Commercial licence, per style",
    url="https://comicraft.com/", price="about $49 a style")


# ------------------------------------------------------------ the picks
#
# Best first, and every "why" is about the BOX TYPE. "A lovely geometric sans"
# says nothing about whether it belongs in a thought bubble.

PICKS: Dict[str, List[Pick]] = {
    # ---- speech and the sub-types that are the same voice at another volume
    "bubble": [
        _g("Comic Neue", "The app's own default: quiet, even colour, and a "
                         "real bold and italic — which dialogue needs, "
                         "because emphasis inside a line is the commonest "
                         "thing in a balloon.", "OFL 1.1"),
        ANIME_ACE,
        WILD_WORDS,
        _g("Gochi Hand", "Rounder and more obviously drawn by hand. Suits a "
                         "lighter, funnier series where Comic Neue reads a "
                         "little neutral."),
    ],
    "narration": [
        _g("Comic Neue", "A caption is a different voice from speech, and "
                         "the cheapest way to say so is the same family at a "
                         "different weight — Regular against the balloon's "
                         "Bold."),
        _g("Caveat", "A narrator who is a character: a diary, a letter, a "
                     "recollection. Do not use it for long captions; it is "
                     "tiring past a couple of lines."),
        _g("Klee One", "A pen-written face with real Japanese glyphs as well "
                       "as Latin, so a caption keeps the page's hand when it "
                       "sits over untranslated signage."),
    ],
    "thought": [
        _g("Comic Neue", "Italic. A thought is the same voice leaning — the "
                         "convention every reader already knows, and the one "
                         "that costs nothing."),
        _g("Shadows Into Light", "A softer, airier hand for a series whose "
                                 "thoughts are meant to feel private rather "
                                 "than merely unspoken."),
        _g("Caveat", "When the thought bubbles are long enough to want a "
                     "face of their own rather than a slant of the speech "
                     "one."),
    ],
    "fancy": [
        _g("Comic Neue", "Italic, the same as a thought bubble — lee's own "
                         "call when the type was split off, so nothing "
                         "already typeset moves. A flash balloon is SPOKEN, "
                         "though, so a face that reads as ornate rather than "
                         "as unvoiced is worth trying."),
        _g("Caveat", "A flourish in the letters to match the flourish round "
                     "them. Suits the flattering, delighted lines these "
                     "balloons usually hold."),
        _g("Chewy", "Rounder and warmer, and upright — for a series where the "
                    "italic reads as a thought however it is labelled."),
    ],
    "shout": [
        _g("Bangers", "The app's default. Drawn rather than merely heavy, and "
                      "narrow, so a long shout still fits the burst it is "
                      "sitting in. It is also the sound effect face, so a "
                      "shouted line and a drawn sound look alike - the burst "
                      "round the one of them is what tells them apart."),
        _g("Jua", "A shout is announced by the BURST it sits in before it is "
                  "read, so the face only has to sound raised - this is a "
                  "fifth heavier than the speech face and full width with it, "
                  "which reads as the same voice louder. Pick it to keep "
                  "shouts and sound effects apart."),
        _g("Luckiest Guy", "Heavy, tight and drawn. The default until "
                           "2026-08-28, and worth reaching for on the one "
                           "line in a chapter that really is a bellow - it is "
                           "too much for every angry or urgent line."),
        _g("Chewy", "Between the two: rounder and heavier than Jua without "
                    "Luckiest Guy's cartoon weight."),
        _g("Titan One", "Rounder and fatter. Good for comedy shouting, where "
                        "Luckiest Guy reads as anger."),
        _g("Anton", "A condensed sans rather than a comic face: for a shout "
                    "that is meant to sound flat and hard rather than "
                    "cartooned."),
    ],
    "whisper": [
        _g("Comic Neue", "Regular, set small. A whisper is the balloon's own "
                         "voice with the volume down, and changing the face "
                         "as well says something the panel did not."),
        _g("Gaegu", "Thin and wobbly, which reads as under-the-breath at a "
                    "size where Comic Neue still reads as ordinary speech."),
        _g("Kalam", "A quick, light hand. Holds up smaller than most comic "
                    "faces before the counters close."),
    ],
    # ---- text out on the artwork
    "freefloat": [
        _g("Comic Neue", "Speech with no balloon round it is still speech. "
                         "Same face, and let the missing balloon do the "
                         "work."),
        _g("Patrick Hand", "Handwriting that sits on artwork without looking "
                           "typeset — which is the whole difficulty with "
                           "text that has no balloon to own it."),
        _g("Yomogi", "Soft and rounded, with Japanese glyphs, for a page "
                     "where the loose lines are meant to feel scribbled in."),
    ],
    "narration_free": [
        _g("Comic Neue", "Narration over art has to survive whatever is "
                         "behind it; an even face with a keyline round it "
                         "does that better than a lively one."),
        _g("Klee One", "A written narrator's voice that still holds a long "
                       "line — and it has the Japanese glyphs if the "
                       "narration quotes any."),
        _g("Zen Kurenaido", "A fine, upright pen hand. Quieter than Caveat "
                            "over busy artwork."),
    ],
    "aside": [
        _g("Comic Neue", "The app's default. An aside is the same character "
                         "at half volume, and the cheapest way to say so is "
                         "the speech face set small - a second hand in the "
                         "margin is a second voice."),
        _g("Patrick Hand", "A mutter is a note in the margin, and this is the "
                           "face for saying so out loud. The default until "
                           "2026-08-28."),
        _g("Gaegu", "Smaller and shakier, for the asides that are meant to "
                    "be almost too small to read."),
        _g("Yusei Magic", "A marker-pen hand with Japanese glyphs — the "
                          "closest free face to the way these are usually "
                          "scrawled in the original."),
    ],
    "sign": [
        _g("Anton", "Signage is PRINTED, not spoken, and a condensed sans is "
                    "what printing looks like — which is the one thing a "
                    "comic face cannot say."),
        _g("Bebas Neue", "Narrower still, all-caps only. For shopfronts and "
                         "banners where the line has to fit a real width."),
        _g("Archivo Black", "When the sign is meant to look official — a "
                            "notice, a warning, a document."),
        _g("Oswald", "The one with a lowercase, for signs that carry a "
                     "sentence rather than a word."),
        _g("Comic Neue", "The app's default for this type, and the safe "
                         "answer for a small label in the corner of a panel: "
                         "a display face at eleven points is just harder to "
                         "read."),
    ],
    # ---- and the effects, which are display type
    "sfx": [
        _g("Bangers", "The app's default for sounds: drawn, condensed, and "
                      "it survives being stretched to fill a box, which is "
                      "what an effect gets asked to do."),
        _g("Dela Gothic One", "Heavy Japanese display with Latin to match — "
                              "the nearest free face to the weight of a "
                              "drawn katakana effect."),
        _g("Bungee", "Built for signage and vertical setting, so it holds "
                     "together at the angles effects get set at."),
        _g("Mochiy Pop One", "Rounder and softer, for the small comic "
                             "sounds — a plop, a squish."),
    ],
    "sfx_big": [
        _g("Dela Gothic One", "An impact effect is the loudest thing on the "
                              "page and this is the heaviest of these — with "
                              "Japanese glyphs, so it can sit beside "
                              "whatever was not erased."),
        _g("Bangers", "Lighter and narrower, and the one to reach for when "
                      "the effect has to cross a whole spread without "
                      "burying the artwork."),
        _g("Rubik Mono One", "Blunt, square and enormous. For mechanical "
                             "impacts — a door, an engine, a gunshot."),
        _g("Train One", "Striped, so the effect reads as drawn rather than "
                        "set. Best very large, where the stripes are "
                        "visible."),
        _g("Rampart One", "Outlined with a 3D shadow built into the glyph, "
                          "for the one effect a page is built around."),
    ],
    "sfx_small": [
        _g("Kalam", "The app's default for background sounds: a quick hand "
                    "that stays readable at the sizes these get set at."),
        _g("Yusei Magic", "A marker hand with Japanese glyphs, for the "
                          "little scratchy ones."),
        _g("Nanum Pen Script", "Thin, fast, and it leans — which is what a "
                               "small background sound looks like when it is "
                               "drawn rather than placed."),
        _g("Gochi Hand", "Rounder, for the soft ones: a rustle, a breath, a "
                         "footstep."),
    ],
}


# ------------------------------------------------- what is already here
#
# A recommendation the person already has installed is not a download, and
# saying so is most of the value of the page: eleven of these need no action
# at all.

def _installed_families(paths) -> set:
    """The family names on this machine, loosely.

    Matched on the file's stem with the style suffix taken off and spaces
    removed - `ComicNeue-Bold.ttf` and `Comic Neue` are the same family, and
    the two spellings are the two halves of this app's font handling: files on
    one side, families on the other.
    """
    out = set()
    for p in paths or ():
        stem = os.path.splitext(os.path.basename(str(p)))[0]
        out.add(stem.split("-")[0].replace(" ", "").replace("_", "").lower())
    return out


def with_availability(paths) -> Dict[str, List[dict]]:
    """`PICKS`, with each entry told whether this machine already has it.

    `paths` is whatever `find_fonts()` gave - every font the app can see,
    installed or in the project's own folder - so a face somebody downloaded
    an hour ago stops being a link the moment it is on disk.
    """
    have = _installed_families(paths)
    out: Dict[str, List[dict]] = {}
    for kind, picks in PICKS.items():
        rows = []
        for p in picks:
            d = p.as_dict()
            d["installed"] = p.family.replace(" ", "").lower() in have
            rows.append(d)
        out[kind] = rows
    return out
