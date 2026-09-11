"""Page-level translation.

The single biggest quality lever in the whole pipeline is translating the
WHOLE PAGE at once, in reading order. Japanese drops subjects and pronouns
constantly; a bubble reading 「来たんだ」 has no subject at all and only the
surrounding dialogue reveals who came. Per-bubble translation cannot recover
that. Page-level translation can.
"""
from __future__ import annotations

import difflib
import http.client
import json
import os
import re
import ssl
from dataclasses import dataclass, field
from typing import Optional

from . import kinds as _kinds
from . import stopping as _stopping
from .models import Page

MODEL = "claude-sonnet-5"

# How many times the reader asks for one piece of a page. Three, so a reply
# that comes back malformed is asked again twice before its regions are given
# up on - the same courtesy translating and proofreading already got, and the
# reason one bad reply no longer ends a chapter.
OCR_TRIES = 3

# Marks that count as a long dash in the source. A SINGLE ー is the ordinary
# long-vowel mark and appears in perfectly normal words, so it is not one; a run
# of two or more is a drawn-out cry and is.
_SRC_DASHES = "—–―─━〜～"

# And the plain hyphen-minus, WHERE IT STANDS ALONE. A scan letters its dashes
# with whatever the keyboard has: the title plate `- 대마법사 김진우 -` frames a
# caption with two of them, and reading that page as having no dash on it cost
# the plate its frame - the translator's "Arsilan - Archmage Kim Jinwoo" was
# turned into "Arsilan, Archmage Kim Jinwoo", which says he IS Arsilan.
# Inside a word the same character is a hyphen and means nothing here, so it
# only counts with whitespace on both sides, or the end of the text. A bulleted
# status window counts too, and that is the right answer for the same reason:
# the page does print dashes there. No `re.M` - a newline IS whitespace, so a
# plate on the third line of a caption is already reached from both sides, and
# a flag that changes nothing is a line that lies about what the code does.
_LOOSE_HYPHEN = re.compile(r"(?:^|\s)-+(?=\s|$)")


def source_has_dash(src: str) -> bool:
    """Did the original punctuate with a long dash?"""
    s = src or ""
    return (any(ch in s for ch in _SRC_DASHES)
            or bool(re.search(r"ー{2,}", s))
            or bool(_LOOSE_HYPHEN.search(s)))


# What a page looks like when it masks its OWN word. Japanese scans do it with
# 〇, ●, × or a full-width asterisk; an already-English scan does it the western
# way. `〇` doubles as the kanji for zero, so a number like 一〇〇 reads as masked
# here - deliberately. Erring that way costs a warning that is not raised; the
# other way costs a warning raised about a page that did nothing wrong.
_SRC_MASKS = "*＊〇○●×✕✖#＃$＄@＠%％"

# What the MODEL does when it censors on its own account: a letter with a mask
# character stuck to it. Both halves are needed - "5 * 4" is arithmetic and
# "WOW!!" is shouting, neither is a masked word.
_MASKED = re.compile(r"[A-Za-z]\*|\*[A-Za-z]|[A-Za-z][#@$%&][#@$%&!*]+")


def added_masking(dst: str, src: str) -> bool:
    """Did the translator mask a word the page itself does not mask?

    lee: *"make sure that ther is not censoreing of any word at all"*, and then
    *"unless it it cenored inth emnga itself you can add * if the managa itselft
    has it"*.

    Softening a swear is a mistranslation - the line was written to land that
    hard - and typesetting it as "f***" when the Japanese says the word outright
    is the model editing the author. Mirroring a mask the page DOES carry is
    the opposite: that mask is part of what the page says.

    Nothing can put the word back once the model has thrown it away, so this
    only reports. Prevention is in the prompt, which now says so in as many
    words.
    """
    return bool(_MASKED.search(dst or "")) and \
        not any(ch in (src or "") for ch in _SRC_MASKS)


CENSOR_NOTE = ("the AI masked a word this page does not mask — "
               "it censored itself, check the line")


# An ellipsis, however it is written. One … or ‥ is already one; ordinary
# periods and the katakana middle dot need a run of two, because a single
# period is a full stop and a single ・ separates the halves of a foreign name.
_ELLIPSIS = r"(?=[…‥]|[.．・]{2})[.．・…‥]+"
# What may stand in front of one and still leave it at the start of the line.
_OPENERS = r"[\"'“”‘’«»「」『』（）()\[\]【】\s]*"

# Where the EDGE of a line is, for a dash. Not the edge of the string: a quote
# or a bracket can stand outside one, and so can an ellipsis, because
# `strip_added_ellipsis` runs after this and is about to take that ellipsis
# away. "...—The existence known as Kim Jinwoo" is a dash at the front of the
# line the reader will be handed, and reading it as an INTERIOR dash turned it
# into a comma and then left the comma behind: ", The existence known as...".
# ...and the PLAIN HYPHEN counts as one of them here, which it does not in
# `source_has_dash`. A line cannot begin with the hyphen of a hyphenated word,
# so a hyphen at the front is a dash whatever the keyboard typed it with -
# lee's page 4 came back "-Be resolute before pain." and walked straight past
# a class that knew only `—` and `–`. At the TAIL it must have a space in
# front of it, or "well-" - a word the speaker was cut off in the middle of -
# would lose its hyphen.
_EDGE_LEAD = re.compile(rf"^({_OPENERS}(?:{_ELLIPSIS})?{_OPENERS})[-—–]+\s*")
_EDGE_TAIL = re.compile(
    rf"(?:\s*[—–]+|\s+-+)({_OPENERS}(?:{_ELLIPSIS})?{_OPENERS})$")


def strip_added_dashes(dst: str, src: str) -> str:
    """Take back dashes the translator put at the edges of a line unbidden.

    Asked to carry one sentence across two balloons, the model reaches for a
    dash at the break - closing the first balloon with one and opening the
    second with another - even when the Japanese has no dash anywhere. Nothing
    in the page called for it, and scanlation does not typeset it that way: a
    thought continuing into the next balloon is trailed with an ellipsis, not a
    rule, and American comics have no em-dash at all. So an edge dash with no
    dash behind it in the source comes straight back off.

    Dashes INSIDE a line are left alone. There the dash is doing a job that
    removing it would leave undone, and the source may well have earned it with
    punctuation of its own.

    The LEADING one is the exception to that exemption, and it is the one lee
    found: a dash at the front of a Korean or Japanese bubble is the page's
    mark for speech arriving from off-panel, and English typesetting has
    never used it - the balloon's own tail says the same thing, and so does the box
    type. So it comes off whether or not the source has one, which is the same
    rule `strip_added_ellipsis` already applies to a leading ellipsis. Without
    that, whether the reader sees it comes down to whether the model felt like
    typing one: lee's page 4 kept its dash and page 25 dropped it, from source
    lines punctuated identically.
    """
    t = (dst or "").strip()
    if not t:
        return dst
    t = _EDGE_LEAD.sub(r"\1", t, count=1)
    if source_has_dash(src):
        return t.strip() or dst
    t = _EDGE_TAIL.sub(r"\1", t, count=1)
    # ...and one in the MIDDLE, which this used to leave alone on the grounds
    # that it was doing a job. Measured over a chapter, the job it was doing
    # was the model's own voice: "Legend of the Dragon 7—a game that earned the
    # approval of..." and "a standard premise—become the hero", from Korean
    # with no dash in it anywhere. A comma says the same thing and a comic font
    # can draw it. The source having ANY dash still buys the whole line an
    # exemption, because then the dash may well be the page's own.
    t = re.sub(r"\s*[—–]+\s*", ", ", t)
    t = re.sub(r",\s*,+", ",", t)
    t = re.sub(r"\s+,", ",", t)
    return t.strip() or dst


_LEADS = re.compile(rf"^({_OPENERS}){_ELLIPSIS}\s*")


def source_leads_with_ellipsis(src: str) -> bool:
    """Does the original OPEN by trailing off?"""
    return bool(_LEADS.match(src or ""))


def strip_added_ellipsis(dst: str, src: str) -> str:
    """Take back an ellipsis the translator opened the line with unbidden.

    lee, looking at 悪女見習いさん come back as *"...little
    villainess-in-training."*: *"remove the ... at the begening if its not on
    teh japanesse text it shoud not exist"*.

    The model opens lines that way to make them sound like continued speech,
    and this prompt used to teach it to: the rule for a sentence carried
    across two balloons said the second one BEGINS with three periods. That is
    a scanlation habit, not the author's punctuation, and it goes on the front
    of standalone lines that continue nothing. A leading ellipsis is a pause
    the reader is asked to hear, and the page did not draw one.

    So the line still ENDS with three periods where a sentence runs on - that
    is the half that reads as trailing off, and lee has kept it everywhere.
    It just never starts with them unless the {source} does.

    Both sides are read past an opening bracket or quote, so 『……そうか』
    counts as having one and `"...well"` counts as being one.
    """
    if not (dst or "").strip() or source_leads_with_ellipsis(src):
        return dst
    t = _LEADS.sub(r"\1", dst, count=1)
    return t.strip() or dst


# Punctuation that can only be standing in front of the words. A quote and a
# bracket are not in this class: they WRAP the line rather than precede it, and
# `¿`/`¡` open a sentence in Spanish, which is one of the targets - so all of
# those are read past on both sides, exactly as `_LEADS` reads past them.
# The hyphen is last because a `-` anywhere else in a character class is a range.
_LEAD_MARKS = r"[,.;:!?…‥・·、。，；：！？—–ー~〜～\-]"
_LEAD_ANY = re.compile(rf"^({_OPENERS})({_LEAD_MARKS}+\s*)")


def leads_with_a_mark(t: str) -> bool:
    """Is there punctuation in front of the first word?"""
    return bool(_LEAD_ANY.match(t or ""))


def strip_added_lead(dst: str, src: str) -> str:
    """Nothing may stand in front of the line that does not stand in front of
    the source.

    lee, on a balloon that came back as *", The existence known as Kim Jinwoo
    has probably ceased to exist."*: *"there isjat anything informt of th text
    in the raw so there shoud be notjing in the transated"*.

    That comma was not the model's. The model wrote `...—The existence known
    as...`; `strip_added_dashes` read a dash with three periods in front of it
    as an INTERIOR dash and made it a comma, and `strip_added_ellipsis`, which
    runs straight after, then took the periods away and left the comma standing
    on its own. Two cleaners, each correct about the thing it was looking at,
    and a result neither of them was looking at.

    So this one does not look at a step. It looks at the finished line, and it
    is the last thing to run. Whatever a future cleaner leaves on the front of
    a line, the rule holds: the source draws it or it goes.
    """
    if not (dst or "").strip() or leads_with_a_mark(src):
        return dst
    m = _LEAD_ANY.match(dst)
    if not m:
        return dst
    return (m.group(1) + dst[m.end():]).strip() or dst

# Any server speaking the OpenAI chat-completions shape works here: Ollama,
# LM Studio, llama.cpp's server, vLLM, or a hosted free tier. What the model
# must be able to do is follow instructions and return JSON - a sentence-level
# MT model (opus-mt, NLLB) cannot, and would throw away the page context that
# makes this pipeline worth having.
LOCAL_PRESETS = {
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "qwen2.5:14b-instruct"},
    "lmstudio": {"base_url": "http://localhost:1234/v1", "model": "local-model"},
    "llamacpp": {"base_url": "http://localhost:8080/v1", "model": "local-model"},
    # Hosted services with a free tier. All speak the OpenAI chat shape.
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "model": "gemini-3.5-flash"},
    "groq": {"base_url": "https://api.groq.com/openai/v1",
             "model": "llama-3.3-70b-versatile"},
    "cerebras": {"base_url": "https://api.cerebras.ai/v1",
                 "model": "llama-3.3-70b"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",
                   "model": "qwen/qwen-2.5-72b-instruct"},
}

# The three the app is for. There was a fourth, "comic" - an English-source
# western comic - and it is gone; lee: *"remove suport for comics and the
# project still supports mahnwa and manhua"*. Nothing else about English is
# gone with it: English is still a source LANGUAGE anyone can pick, which is
# what an already-translated scan needs.
#
# A project.json saved as a comic is migrated on load rather than silently
# reinterpreted as a manga - see `Project.load`.
MEDIA = {
    "manga":  {"source": "Japanese", "rtl": True,  "code": "ja"},
    "manhwa": {"source": "Korean",   "rtl": False, "code": "ko"},
    "manhua": {"source": "Chinese",  "rtl": False, "code": "zh"},
}

TARGETS = {
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
    "fr": "French",
}

# What a source code MEANS. The menus offer three of these; the rest are here
# so that a chapter which already carries one is still understood.
#
# THREE MEDIA, THREE LANGUAGES. lee, going into the beta: *"we will only
# support the original languages so manga jappenesse, mnhawa koren and manhua
# chinesse"*. Everything the app is measured on - the readers, the detectors,
# the honorifics, the reading direction - is built for those three, and
# offering a fourth was offering something nobody had ever run a page through.
#
# The other four are NOT deleted, and the reason is the same one that kept the
# `comic` medium's answers alive when the medium went (see
# `test_an_old_comic_chapter_is_still_an_english_chapter`): every reader falls
# back to `MEDIA[medium]["source"]` for a code it does not know, so deleting
# "en" would turn an old English chapter into a Japanese one silently - read
# by manga-ocr, laid out right to left, with nothing on screen saying why. A
# name that is no longer on the menu costs one line here and stops that.
SOURCE_LANGS = {
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
    # ...not offered any more; understood where a project already says one:
    "en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French",
}

#: The source languages the app OFFERS - one per medium, in the menus' order.
OFFERED_SOURCES = ("ja", "ko", "zh")


def source_language(medium: str, source_code: str = "") -> str:
    """The language the pages are written in.

    An explicit choice wins; otherwise the medium's usual language.
    """
    if source_code and source_code in SOURCE_LANGS:
        return SOURCE_LANGS[source_code]
    return MEDIA.get(medium, MEDIA["manga"])["source"]

# What carries register in each source language, and so must be compensated for.
SOURCE_NOTES = {
    "Japanese": (
        "Japanese pronouns encode character (俺/僕/私/わたくし/あたし) and cannot "
        "be translated directly, so compensate through diction and rhythm. "
        "Keigo versus plain form marks social distance. Subjects are dropped "
        "constantly — use the surrounding lines to work out who is speaking."),
    "Korean": (
        "Korean speech levels (해요체/해체/합쇼체) and honorific infixes mark "
        "social distance precisely; compensate through diction. Titles like "
        "오빠/언니/선배 carry relationship information with no direct equivalent. "
        "Subjects are dropped constantly."),
    "Chinese": (
        "Chinese marks register through word choice and formality of address "
        "rather than inflection. Forms of address (哥/姐/前辈) carry "
        "relationship information. Watch for classical or literary phrasing "
        "used to signal formality or a historical setting."),
    "English": "Preserve the voice and register of the original dialogue.",
}

# Where each target language needs a deliberate decision the source does not make.
TARGET_NOTES = {
    "English": (
        "English has no formal/informal second person, so carry politeness "
        "through word choice and sentence shape."),
    "Spanish": (
        "Choose tú or usted per relationship and keep it consistent for a "
        "character across the chapter."),
    "Portuguese": (
        "Use Brazilian Portuguese unless told otherwise. Choose você or o "
        "senhor / a senhora per relationship and keep it consistent."),
    "French": (
        "Choose tu or vous per relationship and keep it consistent for a "
        "character across the chapter; a switch between them is a story beat "
        "and should only happen if the original marks one."),
}

# HONORIFICS KEPT, WHEN THE PROJECT ASKS FOR THEM.
#
# lee: *"a swith that lets the translator keep glow-san instad of mr glow fo
# rthe tranlsation it shoud keep styff like oni-chan and other stuff like that
# that manga reader like and do it for mnahwa and mahua too"*, and then the
# limit on it: *"it shoud only keep teh very popular managa na manhua and
# manhwa honotifics"*.
#
# So this is an ALLOW-LIST and not a policy. "Keep the honorifics" as an
# instruction gets you 拙者 romanised and 部長 left as "buchou", which is not
# what a scanlation reader is asking for - what they want is the dozen forms of
# address that every release in the genre already keeps, and everything else
# localised the way it would be anyway. A model given a rule rather than a list
# picks its own dozen, and picks a different dozen on the next page.
#
# Each list is the forms that appear untranslated in mainstream scanlation and
# would look wrong translated. Anything not on the list is translated.
HONORIFIC_NOTES = {
    "Japanese": (
        "KEEP JAPANESE HONORIFICS AND FORMS OF ADDRESS, romanised, attached "
        "with a hyphen: -san, -kun, -chan, -sama, -dono, -sensei, -senpai, "
        "-kouhai. "
        "So グロウさん is \"Glow-san\" and NEVER \"Mr. Glow\". Keep the family "
        "terms used as address the same way: onii-chan, onee-chan, nii-san, "
        "nee-san, onii-sama, onee-sama - and senpai and sensei standing alone "
        "as a form of address, with no name. That list is the whole of it. "
        "Every other Japanese word is translated as usual: do not romanise a "
        "job title, a rank, a common noun or a greeting, and do not invent an "
        "honorific the line does not have."),
    "Korean": (
        "KEEP KOREAN HONORIFICS AND FORMS OF ADDRESS, romanised: oppa, unnie, "
        "hyung, noona, sunbae, hoobae, and the suffixes -ssi and -nim "
        "(\"Jinwoo-ssi\", \"seonsaeng-nim\"). Keep them standing alone as "
        "address too, with no name. That list is the whole of it. Every other "
        "Korean word is translated as usual: do not romanise a job title, a "
        "rank, a common noun or a greeting, and do not invent one."),
    "Chinese": (
        "KEEP CHINESE FORMS OF ADDRESS, romanised in pinyin without tone "
        "marks: gege, jiejie, didi, meimei, shizun, shixiong, shijie, shidi, "
        "shimei, and daren as a suffix (\"Wei-daren\"). Keep them standing "
        "alone as address too, with no name. That list is the whole of it. "
        "Every other Chinese word is translated as usual: do not romanise a "
        "job title, a rank, a common noun or a greeting, and do not invent "
        "one."),
}


SYSTEM_TEMPLATE = """You are a professional {medium} localizer and a \
native-level {target} copy editor. You are translating one full page from \
{source} into publication-quality {target} for a scanlation release; the \
page's dialogue arrives in reading order, together with the series context.

Use the context you are given — this is what keeps chapters consistent:
- series_context is the story synopsis, written by the editor. Treat it as
  ground truth for who the characters are, what they are called, how they
  relate, and where the story stands. Resolve dropped subjects and ambiguous
  speakers against it. Never contradict it.
- characters is the running character sheet: pronouns and a voice note per
  character. Use EXACTLY those pronouns and that voice for that character,
  every single line. Add to character_additions ONLY a NAMED, recurring
  character the sheet does not already have — someone with a proper name, or
  a figure who clearly matters to the story — pronouns first, then a short
  voice note ("she/her - haughty noblewoman, formal speech"). Do NOT add
  one-off or unnamed bit parts: a guard, a bystander, a child in the crowd, a
  petitioner, a shopkeeper, the narration voice, "Crowd", "Guard A". Those
  still get a "speaker" label on their own line so you know who is talking,
  but they do NOT belong on the running sheet. When in doubt, leave them off.
  A name has to be PRINTED ON THE PAGE or already in the synopsis or the
  sheet. Never invent one, never guess one from the art, and never coin a
  label to stand in for a name ("the blonde girl", "Knight B", "Mystery Man")
  — an unnamed speaker stays unnamed. If nobody says who is speaking, the
  speaker is null. A character sheet that names people the story has not
  named is worse than an empty one.
- glossary is the canon spelling of every proper noun that is NOT a person:
  places, kingdoms, organizations, titles, ranks, techniques, items, works.
  Follow it exactly, and propose new recurring ones in glossary_additions.
  A person NEVER goes in glossary_additions — a named character belongs in
  character_additions and nowhere else, so no one is listed twice.
- do_not_return, when present, lists fields you must LEAVE OUT of your reply
  entirely. They have been switched off for this project. Do not propose them,
  do not explain that you have not, and do not put an empty one in instead —
  omit the key. A field you were not given (no series_context, no glossary, no
  characters) is one nobody is keeping for this project; translate from the
  page in front of you and do not ask for it.
- EVERY glossary rendering must say what the thing IS, in brackets after the
  name: "Tarel (the copper coin)", "Zaldone (the northern kingdom)". A bare
  name is refused and does not reach the sheet. A glossary that says only
  "Tarel" tells the next page nothing it could not already see.
  If a term you are GIVEN in the glossary has no bracket, propose it again in
  glossary_additions with one. That is the only way an empty one gets filled.

- previous_page_tail is the end of the previous page. Continue from it, so
  sentences and tone flow across the page break.
- already_said, when present, is what THIS chapter has already used: the
  speaker labels on earlier pages, the English you have already given
  recurring source terms, and under `names` every proper name your own
  earlier pages have spelled out. All three are there for one reason — to
  stop the same thing being called two things.
  * **A person the chapter has NAMED keeps the name.** Never coin a role
    label for somebody who has one: Turiss was named on page 11 and came
    back as "Assistant" on page 16, four pages into the same conversation,
    which is two characters as far as the sheet is concerned. A role label
    is for somebody the story has not named at all.
  * A speaker already labelled gets that label again. One person, one name:
    a grandfather who is "Jinwoo's Grandfather" on one page and "Osung Group
    Chairman" four pages later reads as two characters, and the sheet then
    carries both for ever. Pick the more specific of the two and keep it.
  * A source term already rendered is rendered the same way, capitals and
    all. "erosion" on one page and "Erosion" on the next are two terms; so
    are "mana crystals" and "magic stones". If a term is going to come back,
    put it in glossary_additions the FIRST time you use it, which is what
    makes it settled rather than remembered.
  * **A name in `names` is spelled exactly that way again.** This is the one
    that catches people, because a person never goes in the glossary and so
    a character's romanisation is written down in no sheet anywhere: the
    only record of it is that you already used it. A surname you romanised
    four pages ago is not open again — 크리서스 came back "Chrysos" once and
    "Chryses" once, which is two men. If the name in front of you is a
    near-miss of one in `names` — same sound, a letter or two apart — it is
    that name, so use the spelling in the list rather than a new one. Only a
    name that is genuinely somebody else gets a new spelling.

Translate what is written. Read the context to understand the line, then say in
{target} what the {source} says — no added adjectives, no invented names, no
inferred stage directions, nothing "clarified" that the original leaves
implicit. Where the original is plain, be plain. Where it is ambiguous, keep the
ambiguity rather than choosing for the reader. Natural {target} is the goal, not
a freer story.
- chapter_context, when present, is every page of the chapter — finished
  translations where they exist, source lines otherwise. Read it so this
  page fits the whole story, but translate ONLY the regions in this
  request.

Translation rules:
- Translate for natural {target} readability, not literal fidelity. Match the
  register of the original: rough speech stays rough, polite speech stays
  polite. Write as a native {target} speaker would actually say it.
- A speech bubble is a person TALKING. Write it the way that person would say
  it out loud — a full, natural spoken sentence with its normal connecting
  words. NEVER turn dialogue into a headline, a label, or a colon-and-list
  ("FIRST PRIORITY: HEAL YOUR INJURY — OR HESTER LEARNS MAGIC"). That reads
  like a caption, not speech. Say it like a person: "First thing's healing
  your wound — or getting Hester to learn magic." Keep the connective flow
  ("what we do first is…", "either… or…") that makes it sound spoken.
- Narration boxes and captions may be more clipped or formal; speech bubbles
  and thoughts must sound like a living voice.
- Some regions carry a "link" number. Regions sharing the SAME "link" value are
  ONE continuous sentence broken across several bubbles, in reading order.
  Translate them as a single flowing line and split it naturally across those
  bubbles — each bubble holds its own part, and read in order they form one
  sentence. Never translate a linked region as a self-contained line, and never
  repeat the whole sentence in each bubble.
- WHEN YOU SPLIT A LINKED LINE, THE PUNCTUATION GOES WHERE THE SOURCE PUT IT.
  Each box keeps the trailing marks ITS OWN source line ends with, and gets
  none that it does not. し and ん… linked are "SI" and "LENCE..." - the dots
  are drawn in the second box, so they belong to the second box, and "SI..."
  followed by "LENCE" is wrong however natural it looks. The split point in
  the words is yours to choose; where the author's dots live is not.
- A link between SOUND EFFECTS means the same thing about a sound: one effect
  the artist drew across the page with a gap in it, not two sounds. し and ん…
  linked are しん… — a hush, one word. So read them together and split the
  English at the same place, so that what lands in the first box and what
  lands in the second are the two parts of one sound. Never make two sounds
  of it, and never put the whole of it in both boxes.
- Two SOUND EFFECTS that plainly form one drawn sound may be split the same
  way even where no link joins them — し then ん… is しん… whether or not
  anybody linked the boxes, and the English splits where the drawing splits.
  DIALOGUE is not like that: without a link, every bubble is its own complete
  line, and a sentence is never carried from one unlinked bubble into the next.
- A "balloon" number is a DIFFERENT thing and must not be treated the same
  way. It means the artist drew those regions as two lobes of one balloon —
  a fact about the picture, not about the words. A double balloon holds two
  separate sentences as often as one. So translate each of them for what it
  says, ending each as its own punctuation ends it, and only let them run on
  into one another where the SOURCE runs on. Do not weld two complete
  sentences together with a comma, and do not open the second one with "and"
  or "but" unless the Korean does.
- {source_note}
- {target_note}{honorific_note}
- A SOUND EFFECT AND OUTSIDE TEXT ARE TOLD APART BY THE WORDS, and you are
  the first thing in the pipeline that can read them. The box finder labels a
  region from its SHAPE - loose text on the artwork, no balloon - and shape
  cannot tell a drawn crash from a muttered aside. So when a region arrives as
  "sfx" or "freefloat" and the words are plainly the other one, say so: put
  "kind" on that region in your reply, "sfx" or "freefloat".
  * "sfx" is a NOISE: an impact, a movement, a texture, a heartbeat - ドン,
    ざわざわ, ドキドキ. It has no grammar and nobody says it.
  * "freefloat" is somebody TALKING or THINKING off-balloon - a muttered
    aside, an unvoiced thought, a label, a sign, a caption on the art.
  * Change it ONLY between those two, and only when the words settle it.
    Never propose a kind for a region that arrived as anything else, never
    for a bubble, and leave "kind" out entirely when the label it came with
    is right - which is most of them.
- Work out WHO SPEAKS each line before translating it — from the reading
  order, the synopsis, the character sheet and the dialogue itself — and
  fill in "speaker". Steady speaker attribution is what keeps pronouns
  steady; most pronoun mistakes are speaker mistakes.
- NEVER invent a name. Use a proper name for a speaker only if that name is
  on the character sheet, in the synopsis, or written on the page — someone
  is addressed by it, or it is printed in the text. If you do not know who
  someone is, label them by what they are: "Attendant", "Guard", "Boy",
  "Woman in the crowd". A plain role label is always correct; a made-up name
  is a lie that the character sheet then carries into every later chapter.
- Pronouns and gender follow the character sheet and the synopsis. If a
  line's subject is genuinely unknowable even with the context, prefer a
  rendering that avoids committing to a pronoun over guessing one.
- Spell every character's name EXACTLY as the character sheet and glossary
  do — never invent an alternative romanization for a name that is already
  on the sheet.
- LENGTH IS NOT A CONSTRAINT ON YOU. Say what the {source} says. Never cut a
  word, a qualifier or a nuance to make a line shorter, and never pad one out
  to fill a balloon — the balloon is the typesetter's problem and it is
  already solved: the type is set smaller. A line that fits and does not say
  what the page says is the worst line on the page.
  Being NATURAL is still a constraint, and a different one: the shortest
  wording that carries the whole meaning is the right wording, because that is
  how people talk, not because of the space. Do not translate long.
- Honorifics may be retained where they carry meaning the target language
  cannot.
- A RUN of marks is part of the line and is copied as a run. "!!!" is three
  and "?!!" is three, and they are drawn at the size the artist drew them:
  `이건 기적이야!!!` cut down to "This is a miracle!" is a quieter line than the
  one on the page. Shortening is about WORDS and never about punctuation.
- Use plain punctuation that comic typesetting fonts can actually draw:
  straight apostrophes and quotes, three periods for an ellipsis, and a
  hyphen only inside a hyphenated word.
- A MARK THE SOURCE LINE CARRIES STAYS ON IT, in the same place. A heart, a
  star, a music note, a sparkle, a sweat drop, an anger mark: `これから本番♥`
  is "This is the real thing♥" and never "This is the real thing". The mark is
  part of what the balloon says — it is the difference between a line and a
  flirt — and it is not punctuation to be tidied. Keep the same number of
  them: `♥♥` is two.
  This does NOT let you add one. A mark the {source} does not have is
  decoration you invented, and it goes on the page as though the artist drew
  it.
- NEVER introduce a dash the original does not have. A sentence continuing
  into the next bubble ENDS with three periods — not with a dash. Use a dash
  only where the {source} itself carries one (—, ─, ━, 〜 or a run of ー).
- Never START a line with an ellipsis the {source} does not start with. The
  trailing end of a carried sentence reads as trailing off; three periods on
  the FRONT of the next bubble is a scanlation habit, and on a line that
  continues nothing it is a pause the artist never drew. Open with the first
  word.
- WHAT MAY APPEAR IN THE LINE: letters of the target language, plain
  punctuation, and the marks the {source} line itself carries. Source-language
  punctuation is not — 。、！？ come across as the target's own. Nor is a
  symbol you reached for yourself.
  (This read "decorative symbols and music notes are not" until the app could
  draw them. It was right while a comic face had no glyph for a heart and one
  in the line came out as an empty box on the page; it is wrong now, and the
  rule it has become is the one above: the SOURCE decides, not taste.)
- Sound effects: render as a comic SFX in {target} ("CRASH", "THUD"), not a
  sentence. Typeset it as a typesetter would DRAW it — bare. Never wrap a sound
  in asterisks: *TURN* is chat, not typesetting. Write TURN.
- THE WORDS OUTRANK THE LABEL. A region marked "sfx" that holds an actual
  sentence — a subject, a verb, particles, a name — is SPEECH that was boxed
  wrong, and you translate it as speech: a line of dialogue, punctuated,
  sentence case. Painted, hand-drawn and unboxed writing is labelled "sfx"
  because it is DRAWN, and a drawn shout is still something a person said.
  Never squeeze a sentence into "CRASH" to satisfy its label. The rule does not
  run the other way: a region marked "bubble" holding a bare sound is still a
  sound, which is the rule further down this list.
- THE KANA SAY THE SHAPE OF THE SOUND, and the English has to have the same
  shape. The source writes duration and stop into the spelling, and it is the
  one part of a sound effect you are not guessing at:
  * a trailing small っ/ッ CUTS THE SOUND OFF. End the English on a hard
    consonant — TAP, CLACK, PERK, SHK. Never on a hiss or a held vowel: セッ
    is a clipped sound and "SHFF" is a sustained one, which is the opposite of
    what the page drew.
  * a trailing ー, 〜 or a repeated vowel HOLDS it. Lengthen the English to
    match: ザブーン is SPLAAASH, not SPLASH.
  * a trailing … lets it FADE. Let the English trail off too.
  * a repeated kana is a repeated sound, and repeats in the English.
- ONE DRAWN SOUND, ONE ENGLISH WORD — and one English word for one drawn
  sound. `already_said.sounds` is what this chapter has settled so far: if a
  sound is in that list, use the word it already has. If it is not, pick a
  word that is NOT already spoken for in that list. Two sounds the artist drew
  differently must not arrive as the same word — ザブン is a body going under
  and バチャ is a splatter, and printing both as SPLASH throws away a
  distinction that was drawn on purpose.
- NEVER censor. If a line swears, typeset the swear in full. Softening it to a
  milder word, or masking letters with *, #, @ or $, is a mistranslation: the
  author chose how hard that line lands and it is not yours to move. The only
  exception is a page that masks its OWN word — then mirror the page's masking
  exactly, and only then.
- A bubble that is a WORDLESS SOUND rather than speech — a breath, gasp, pant,
  sigh, sob, hum, scream, groan or similar — is onomatopoeia too, even when it
  sits in a normal bubble. Render it as the {target} SOUND it represents, NOT
  as a phonetic transliteration of the kana. Read the picture to tell which
  sound it is: an intake of breath is "Hahh" or "HHK", a long exhale is
  "Haahh", panting is "Huff... huff...", a sniffle is "SNFF", a whimper
  "Nngh...". So すー… is an inhale ("Hahh..."), NOT
  "Sooo...", and ゼー… is laboured breathing ("HAAAH"), NOT "Zeh...". When it
  is clearly a plain non-verbal reaction give the plain English sound; only
  keep a stylised transliteration when the sound has no natural {target}
  equivalent.

Quality gate — do this before you answer:
- Re-read every line as a {target} copy editor: subject-verb agreement,
  tense, articles, spelling, punctuation. No calques, no stiff
  machine-translation phrasing. Every line must read as if it had been
  written in {target} first.
- Check every pronoun on the page against the character sheet one more time.
- Return ONLY valid JSON matching the schema. No prose, no markdown fences.
  Inside JSON strings, escape every double quote as \\" and write line
  breaks as \\n — an unescaped quote breaks the whole page."""


# THE TRAILING DOTS BELONG TO THE BOX THE ARTIST DREW THEM IN.
#
# lee, over a linked pair - `し` and `ん…` drawn as one しん… across a panel -
# that came back "SI..." and "LENCE": *"becasue these are linked teh ai messes
# up whickh one had the ......"*.
#
# The split itself was right; the punctuation went to the wrong half. And the
# model has no way to get it reliably right, because it is being asked to break
# one English word across two boxes and decide where the author's pause lives
# at the same time. The second is not a judgement at all - the page SAYS which
# box has the dots. `し` has none and `ん…` has them, so the English is "SI" and
# "LENCE...", every time, whatever the model returned.
#
# ONLY INSIDE A LINK, and only the trailing dots. A standalone line that trails
# off keeps its ellipsis whether or not the Japanese drew one - lee has kept
# that everywhere, and `strip_added_ellipsis` says so about the other end of
# the line. What is different here is that the box boundary is not the author's:
# a linked pair is one drawn mark that got cut in two, so the dots are a fact
# about the source and not a choice about the English.
_TAIL_DOTS = re.compile(r"(?:\.{2,}|[…‥]+|・{2,}|。{2,})\s*$")


def _dotted(t: str) -> bool:
    """Does this end in an ellipsis, in either language's spelling?"""
    return bool(_TAIL_DOTS.search((t or "").rstrip()))


def _undot(t: str) -> str:
    return _TAIL_DOTS.sub("", (t or "").rstrip()).rstrip()


def fix_linked_tails(regions, note: bool = False) -> int:
    """Put every linked box's trailing ellipsis where its own source has one.

    Returns how many lines were changed, which is what the run report counts.

    `note` marks the region, and PROOFREADING passes it - lee: *"proffreading
    shud also catch stuff like this"*. At translation time this is one of a
    dozen things being settled and a note on every one would be noise; at
    proofreading it is a correction to a finished line, which is the thing the
    proofread report exists to show. The report already prints the wording it
    replaced, so the note only has to say WHY it moved.
    """
    groups: dict = {}
    for r in regions:
        link = int(getattr(r, "link", 0) or 0)
        # A `balloon` link is a fact about the PICTURE - two lobes of one
        # balloon - and says nothing about one mark being cut in two. Only a
        # real link is one thing split.
        if link and getattr(r, "link_kind", "") != "balloon":
            groups.setdefault(link, []).append(r)
    fixed = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        for r in group:
            dst = (getattr(r, "dst_text", "") or "").strip()
            if not dst:
                continue
            want = _dotted(getattr(r, "src_text", "") or "")
            if want == _dotted(dst):
                continue
            new = (_undot(dst) + "...") if want else _undot(dst)
            if new and new != dst:
                r.dst_text = new
                fixed += 1
                if note:
                    r.flagged = ((getattr(r, "flagged", "") or "")
                                 + " ellipsis: the dots belong to the box whose"
                                   " original has them").strip()
    return fixed


# THE ONLY TWO KINDS A READING MAY SWAP BETWEEN.
#
# lee: *"the tranlator or read text shoiud tun sfx into outside text or turn
# outside text into sfx only those 2"*. The pair is the whole rule, and the
# "only those 2" is the safety in it: both are LOOSE TEXT ON THE ARTWORK with
# no balloon round them, which is exactly why the box finder cannot tell them
# apart - it is working from shape, and they have the same shape. Everything
# else a box can be says something about the picture that the words cannot
# overrule, and a bubble is a bubble whatever is written in it.
RETYPE_KINDS = ("sfx", "freefloat")


def _retype(region, item, ctx) -> bool:
    """Let the reading correct a sound effect that is an aside, or the reverse.

    Refused unless the project asked for it, unless the region is already in
    one of the two FAMILIES, and unless the answer is the other one. A model
    that proposes "bubble", or proposes the family a region is already in, is
    ignored rather than argued with.

    ## Families, not exact kinds

    This compared `region.kind` against the pair directly, and that was right
    for exactly as long as a loose box could only ever BE `sfx` or
    `freefloat`. Read text now labels sub-types, so an effect comes out of it
    as `sfx_big` - which is not in the pair, so the retype was refused and
    lee's switch quietly stopped working on every effect the labeller touched.

    A sub-type is a kind of its family and nothing about `sfx_big` says it
    cannot be outside text; it says the opposite, that somebody thought it was
    a big sound. So the question is asked of the family.

    The whole sub-type goes when the family does. `sfx_big` is not a kind of
    outside text and there is no honest translation of it into one - the box
    lands on the family's own default and can be sub-typed again from there.
    """
    if not getattr(ctx, "retype_kinds", False):
        return False
    want = str(item.get("kind") or "").strip().lower()
    if want not in RETYPE_KINDS:
        return False
    now = str(getattr(region, "kind", "") or "").strip().lower()
    fam = _kinds.family_of(now)
    if fam not in RETYPE_KINDS or fam == want:
        return False
    region.kind = want
    region.flagged = ((getattr(region, "flagged", "") or "")
                      + " kind: read as %s rather than %s" % (want, now)).strip()
    return True


def build_system(medium: str = "manga", target: str = "en",
                 source: str = "", honorifics: bool = False) -> str:
    """The system prompt for one project.

    `honorifics` keeps the genre's forms of address in the English rather than
    localising them - "Glow-san", not "Mr. Glow". Off by default, because it is
    a house-style decision and the house is the person releasing the chapter;
    a reader who wants "Mr. Glow" is not wrong. See `HONORIFIC_NOTES`, which is
    a short list on purpose.
    """
    src = source_language(medium, source)
    tgt = TARGETS.get(target, "English")
    note = HONORIFIC_NOTES.get(src, "") if honorifics else ""
    return SYSTEM_TEMPLATE.format(
        medium=medium, source=src, target=tgt,
        source_note=SOURCE_NOTES.get(src, ""),
        target_note=TARGET_NOTES.get(tgt, ""),
        honorific_note=("\n- " + note) if note else "",
    )


SYSTEM = build_system()

SCHEMA_HINT = """Return:
{"regions":[{"id":<int>,"translation":<str>,
"speaker":<str|null>,"confidence":<0..1>,
"kind":"sfx"|"freefloat" (OPTIONAL — only when the region's given kind is one
  of those two and the words are plainly the other; leave it out otherwise)}],
"page_notes":<str>,
"glossary_additions":{<source term>:"<canon rendering> (<what it is>)"}
  (the bracket is REQUIRED — "Tarel (the copper coin)", never bare "Tarel";
  no people — never a named character, only places/organizations/titles/items),
"character_additions":{<name>:<pronouns, then a short voice note>}}"""


# ------------------------------------------------------------- proofreading

PROOFREAD_TEMPLATE = """You are the copy editor on a professional {medium} \
typesetting team, polishing the {target} script one page at a time.

You receive the series context, the character sheet, the glossary, the last
few lines of the previous page, and every region on the page: the original
{source} line next to the current {target} line, in reading order, with the
speaker each line belongs to. Each region carries its "kind" — "bubble" is
spoken dialogue, "freefloat" is a thought or aside floating on the art,
"narration" is a caption box — and each reads differently: dialogue sounds
like the character's voice, thoughts are looser, narration is composed.
Sound effects are not sent to you at all; they are typeset as-is.

Go through every region and fix ONLY what is wrong:
- NEVER censor, and never un-swear a line that swears. Masking letters with *,
  #, @ or $, or swapping in a milder word, is a change to what the page says,
  not a copy edit. Leave a mask alone only where the page itself carries one.
- Lines that do not read as natural {target}, or do not make sense on their
  own or against the {source} original: rewrite them so they do. Read each
  line aloud in your head. If nobody would say it that way, it is wrong even
  when every individual word is defensible.
- A "bubble" that reads like a HEADLINE, LABEL or colon-list instead of
  someone talking ("FIRST PRIORITY: HEAL YOUR INJURY — OR HESTER LEARNS
  MAGIC") is WRONG: rewrite it as natural spoken speech with its connecting
  words ("First thing's healing your wound — or getting Hester to learn
  magic"). Narration/caption boxes may stay clipped; dialogue may not.
- Read the page as a CONVERSATION, not a list. Each line has to follow from
  the one before it, and the first line has to follow from
  previous_page_tail. An answer that does not answer the question that was
  asked is a mistranslation even when it is a fine sentence.
- Regions sharing the same non-zero "link" are ONE sentence split across
  bubbles. Proofread them as that one sentence and hand the halves back
  still split at the same place. Never repeat the whole sentence in both.
- PRONOUNS. The character sheet gives each named person their pronouns. When
  a line refers to someone the sheet covers, the pronouns must be the
  sheet's. If a line calls Leonora "he" and the sheet says she/her, fix it.
  Fix it in the speaker's own lines too — a character does not misgender the
  person standing in front of them. Where you cannot tell who a pronoun
  points at, LEAVE THE LINE ALONE and say so in page_notes; a confident
  wrong guess about who "he" is does more damage than an unfixed line.
- Character names: the character sheet's spellings are CANON. If a line
  spells a name any other way — a different romanization, a typo, a
  nickname the sheet does not use — rewrite it to the sheet's exact
  spelling. The glossary's renderings of recurring terms and place names are
  equally canon: one place, one spelling, every page.
- LINKED BOXES: check which one the dots belong to. Regions sharing a
  non-zero "link" are ONE mark the artist drew and the box finder cut in two,
  so the trailing ellipsis goes on the box whose ORIGINAL line ends with one -
  し and ん… are "SI" and "LENCE...", never "SI..." and "LENCE". It reads
  equally well either way, which is exactly why it goes wrong; the page
  settles it, so do not choose.
- HONORIFICS are the project's decision and not yours. "keep_honorifics" in
  the request says which way it went. True: a Japanese honorific already on a
  name — -san, -sama, -chan, -kun, -dono — STAYS exactly as it is, and
  "Glow-san" is never tidied into "Glow" or into "Mr. Glow". False: one that
  survived translation comes off. Either way it is the same choice on every
  line of the page, and it is not a matter of what reads better.
- Do not use a proper name the character sheet and glossary do not contain.
  If the current line names somebody the sheet does not know, leave the name
  as it stands and note it; do not "correct" it into a name you recognise.
- Grammar, tense, agreement, spelling, punctuation.
- CONSISTENCY across the whole page and against everything you were given.
  One person, one name, one spelling, one set of pronouns, one way of being
  addressed. One term, one rendering — a title, a rank, a technique, a place
  is translated the same way in every line it appears in. A form of address
  between two characters does not change from bubble to bubble unless the
  {source} changes it. Where two lines disagree, the character sheet and the
  glossary decide; where they say nothing, the FIRST use on the page decides
  and the rest are brought into line with it.

Rules:
- A line that is already right comes back UNCHANGED, character for
  character. Do not rephrase for taste; this is a proofread, not a rewrite.
- Do not invent. No name that is not printed on the page or already in the
  sheet or the glossary, no detail the {source} does not state, nothing
  "clarified" that the original leaves implicit. Staying close to what was
  written is the job.
- Length is not yours to police. Making a line shorter so it fits is a
  change to what the page says, and the page wins; the typesetter sets
  smaller type. Do not pad one out either.
- Plain punctuation only: straight quotes, three periods for an ellipsis, a
  hyphen only inside a hyphenated word.
- A MARK IS NOT PUNCTUATION AND IS NOT YOURS TO TIDY. A heart, star, music
  note, sparkle, sweat drop or anger mark in the current line stays exactly
  where it is, in the same number. The rule above is about quotes and dashes;
  removing a ♥ under it deletes something the artist typeset. Take one off
  only when the {source} line has none — and say so in page_notes.
- Do NOT add a dash the {source} does not have — least of all at the start or
  end of a line to mark a sentence carried across bubbles. That is three
  periods at the END, not a dash. Remove any dash you find used that way.
- A line that STARTS with a dash loses it even when the {source} line starts
  with one. That mark means the speech is coming from off-panel, and English
  typesetting says that with the balloon rather than with punctuation.
- Remove an ellipsis at the START of a line unless the {source} line starts
  with one too. It is a pause the page does not have.
- page_notes is for what you could NOT fix: a pronoun whose referent is
  unclear, a line whose {source} original looks misread, a name nobody on
  the sheet accounts for. One short sentence each, or "" if the page was
  clean. Do not list the things you did fix.
- Every remark must START with the box it is about, written exactly as
  "Box 5:" (or "Boxes 5, 7:" for more than one), using the id given for that
  region. A remark with no box named is unusable: the person reading it has
  to search the whole page for what you meant.
- Return ONLY valid JSON matching the schema. Escape every double quote
  inside strings as \\" and write line breaks as \\n."""

PROOFREAD_SCHEMA_HINT = """Return:
{"regions":[{"id":<int>,"text":<str>}],"page_notes":<str>}"""


def build_proofread_system(medium: str = "manga", target: str = "en",
                           source: str = "") -> str:
    src = source_language(medium, source)
    tgt = TARGETS.get(target, "English")
    return PROOFREAD_TEMPLATE.format(medium=medium, source=src, target=tgt)


def build_proofread_payload(page: Page, ctx: SeriesContext) -> dict:
    # Fixed first, moving last - see `_base_payload` for why the ORDER of
    # these keys is what decides whether a prompt cache can help.
    return {
        "medium": ctx.medium,
        "source_language": source_language(ctx.medium,
                                           getattr(ctx, "source", "")),
        "target_language": TARGETS.get(ctx.target, "English"),
        # THE SAME FIELD THE TRANSLATOR GETS, and it was missing here.
        #
        # `keep_honorifics` reached `_base_payload` and stopped there, so the
        # translator was told to keep -san and the copy editor two steps later
        # was told nothing at all. Measured on lee's chapter 3 with the real
        # prompt: 019's `やっぱりグロウさんなんか嫌い` came back "I really don't
        # like Glow-san." and the proofreader returned "...like Glow.", quietly
        # undoing a setting somebody had switched on - and it did it under two
        # different versions of the prompt, so it is the missing field and not
        # a bad turn.
        "keep_honorifics": ctx.honorifics,
        "series_context": ctx.synopsis,
        "glossary": ctx.glossary,
        # ---- everything below here changes from page to page ----
        "characters": dict(getattr(ctx, "characters", {}) or {}),
        # The last few lines of the page before, with their speakers. A page
        # read in isolation cannot tell that its first bubble is answering a
        # question asked two panels ago, so it cannot tell when the answer
        # does not fit the question.
        "previous_page_tail": list(
            getattr(ctx, "previous_page_tail", None) or [])[-6:],
        "regions": [
            {"id": r.id, "kind": r.kind,
             # who is talking, so pronouns can be checked against the sheet
             # instead of guessed from the line alone
             "speaker": r.speaker or "",
             # same positive link id = one sentence split across bubbles;
             # each half is only correct as part of the whole
             "link": getattr(r, "link", 0) or 0,
             "source": r.src_text, "current": r.dst_text}
            for r in page.ordered()
            # SFX stay out: "CRASH" needs no copy edit, and a model asked to
            # polish one tends to turn it into a sentence.
            #
            # THE FAMILY, and this read `r.kind != "sfx"` until Read text began
            # labelling sub-types. A box that came out of it as `sfx_big` is not
            # the string "sfx", so every labelled sound effect started arriving
            # at the copy editor - paid for by the box, and handed to the one
            # model most likely to turn DOOM into a sentence. The exclusion was
            # always about the family; the string only worked while the two were
            # the same thing.
            #
            # A text box somebody added themselves stays out too. There is no
            # source for the proofreader to check it against, and those are not
            # a translation to be corrected - they are what the person wanted
            # the page to say.
            if ((r.dst_text or "").strip()
                and _kinds.family_of(getattr(r, "kind", "") or "") != "sfx"
                and not getattr(r, "own_text", False))
        ],
    }


def proofread_page(
    page: Page,
    ctx: Optional[SeriesContext] = None,
    client=None,
    model: str = MODEL,
    max_retries: int = 2,
) -> dict:
    """Re-reads every translated region: fixes lines that do not make sense
    and rewrites character names to the sheet's exact spellings. Corrected
    text lands back in dst_text; the reply dict is returned."""
    ctx = ctx or SeriesContext()
    payload = build_proofread_payload(page, ctx)
    if not payload["regions"]:
        return {}

    kind = "anthropic"
    if client is None:
        client, model, kind = make_client(
            backend=ctx.backend, base_url=ctx.base_url,
            model=ctx.model, api_key=ctx.api_key,
            safety=getattr(ctx, "safety", "") or "",
            step_name=getattr(ctx, "step_name", "") or "")
    elif isinstance(client, OpenAICompatClient):
        kind, model = "openai", client.model

    want = {r["id"] for r in payload["regions"]}
    last_err = ""

    for attempt in range(max_retries + 1):
        user = (json.dumps(payload, ensure_ascii=False, indent=1)
                + "\n\n" + PROOFREAD_SCHEMA_HINT)
        if last_err:
            user += f"\n\nYour previous reply was rejected: {last_err}. Fix it."

        _cap = 8000
        if attempt == 0 and not last_err:
            from . import coins as _c
            _cap = _c.reply_cap("proofread",
                                len(payload.get("regions") or []),
                                sum(len(str(r.get("text") or ""))
                                    for r in (payload.get("regions") or [])),
                                model)
        text = _ask(client, kind, model,
                    build_proofread_system(ctx.medium, ctx.target,
                                           getattr(ctx, "source", "")), user,
                    max_tokens=_cap)
        try:
            data = _extract_json(text)
        except Exception as e:
            last_err = ("your reply was cut off — answer tersely"
                        if _looks_truncated(text)
                        else f"invalid JSON ({e}) — escape every double "
                             "quote inside strings as \\\"")
            continue

        items = [it for it in (data.get("regions") or [])
                 if isinstance(it, dict)]
        try:
            got = {int(it["id"]) for it in items}
        except (KeyError, TypeError, ValueError):
            last_err = "every entry in regions needs a numeric id"
            continue
        if got != want:
            last_err = (f"id mismatch: missing {sorted(want - got)}, "
                        f"extra {sorted(got - want)}")
            continue

        from .typeset import normalize_text
        by_id = {r.id: r for r in page.regions}
        for item in items:
            r = by_id[int(item["id"])]
            fixed = normalize_text(str(item.get("text") or "").strip())
            if fixed:
                r.dst_text = strip_added_lead(
                    strip_added_ellipsis(
                        strip_added_dashes(fixed, r.src_text), r.src_text),
                    r.src_text)
                # This run's notes replace the last run's - see the same
                # comment in `translate_page`, and the fourteen doubled
                # remarks in lee's chapter 3 report that found it.
                from .ocr import looks_like_garbage
                r.flagged = looks_like_garbage(r.src_text, r) or ""
                if added_masking(r.dst_text, r.src_text):
                    r.flagged = (r.flagged or "") + " " + CENSOR_NOTE
                note = (quieter(r.dst_text, r.src_text)
                        or stops_short(r.dst_text, r.src_text)
                        or too_long(r.dst_text, r,
                                    getattr(ctx, "min_font", 12)))
                if note:
                    r.flagged = ((r.flagged or "") + " " + note).strip()

        # The model has had its say. Now check its spelling the way a style
        # sheet does - mechanically, against the sheet and glossary, on a page
        # that has no idea what the other thirty-eight pages called this
        # person. This is the half of "consistent" that a prompt cannot
        # promise, because each page looks perfectly consistent with itself.
        table = canon_terms(ctx)
        if table:
            common = observed_lowercase(
                [r.dst_text or "" for r in page.regions]
                + list(getattr(ctx, "previous_page_tail", None) or []))
            renamed: list[str] = []
            for r in page.regions:
                if not (r.dst_text or "").strip():
                    continue
                new, notes = enforce_spellings(r.dst_text, table, common)
                r.dst_text = new
                # a rewrite is settled and only worth reporting in the
                # summary; a near-miss is undecided and belongs on the region,
                # where the person doing the reviewing will see it
                renamed += [n for n in notes if " -> " in n]
                unsure = [n for n in notes if " -> " not in n]
                if unsure:
                    r.flagged = ((r.flagged or "") + " " + "; ".join(unsure)
                                 ).strip()
            if renamed:
                data["spelling_fixed"] = renamed
        # ...and again after the copy edit, for the same reason it runs after
        # the translation: the proofreader is reading one box at a time and
        # will happily move an ellipsis onto the half that reads better. Where
        # the author's dots live is not a copy-editing decision. See
        # `fix_linked_tails`.
        fix_linked_tails(page.regions, note=True)
        return data

    raise RuntimeError(
        f"proofread failed after {max_retries + 1} attempts: {last_err}")


@dataclass
class SeriesContext:
    """Persistent state. Without this, chapter 3 says 'Saint Leonora' and
    chapter 4 says 'Holy Maiden Leonora'."""

    # What the series is called. lee: *"in teh symo[psis tab add a tilee box
    # fort the manga"*. It is content, not configuration, so it lives with the
    # synopsis and the cast and travels with them - and it is what the story
    # context and the chapter file are named after, because "mangatl-project"
    # is not the name of anybody's manga.
    title: str = ""
    synopsis: str = ""
    glossary: dict[str, str] = field(default_factory=dict)
    # name -> "pronouns, voice note". Grown automatically page by page; this
    # is what stops pronouns drifting mid-chapter once the synopsis's named
    # cast is off screen.
    characters: dict[str, str] = field(default_factory=dict)
    previous_page_tail: list[str] = field(default_factory=list)
    # What this chapter has already called people and things - see
    # `already_said`. Filled as a run goes and thrown away with it, which is
    # the right lifetime: it is about one chapter being consistent with
    # itself, and the sheet and the glossary are what carry across chapters.
    # The type sizes this project will set between. `min_font` is the one that
    # is still asked a question: it is the FLOOR, and `too_long` uses it to ask
    # whether a line goes in at all. Nothing budgets against `max_font` any
    # more - no length budget reaches the model at all, see `_base_payload`.
    # The typesetter's own copies are `TypesetConfig.min_font` and `.max_font`.
    min_font: int = 12
    max_font: int = 34
    speakers_seen: list[str] = field(default_factory=list)
    terms_seen: dict[str, str] = field(default_factory=dict)
    # ...and the proper names this chapter's ENGLISH has already used. The
    # other two do not cover it: a speaker label is what a box is tagged with
    # and a term is something somebody proposed, while this is what the PROSE
    # said. lee's chapter called one man Chrysos on page 41 and Chryses on
    # page 45, in the body of two narration boxes, and nothing anywhere had
    # ever written the name down. See `names_in`.
    names_seen: list[str] = field(default_factory=list)
    # ...and the SOUNDS this chapter has already given an English word to.
    #
    # The same argument as `terms_seen`, on the part of a chapter where the
    # drift is easiest to see. A page is translated in its own request, so a
    # full-chapter run is twenty-three requests and not one: page 22 is
    # answered without knowing what page 21 decided. Measured over all fifty
    # sound effects in lee's chapter:
    #
    #   スッ -> SHH on 021 and SWISH on 022
    #   ぱっ -> PERK on 010 and BEAM on 022
    #   SPLASH for ザブン, ザボンッ and バチャ three times - a body going under
    #     and a splatter, drawn as two sounds and printed as one word
    #   SWISH for サラッ as well as スッ, so スッ collides in both directions
    #
    # Sixteen of the fifty are caught in one or the other. Fifty sounds is a
    # few hundred tokens: the cheapest consistency this app can buy.
    sounds_seen: dict[str, str] = field(default_factory=dict)
    # THE STORY SWITCHES. lee: *"add a story setting that allow the user ti
    # turn the story thing off, and to tun what the ai detects with check
    # boxes"*.
    #
    # `story` off means the synopsis, the character sheet and the glossary are
    # neither SENT with a page nor ADDED TO by what comes back. The sheets are
    # not touched - turning it on again finds them exactly as they were, which
    # is the difference between a switch and a delete.
    #
    # The other three are independent, and each is off-able on its own because
    # they fail differently: a series with a huge cast wants the character
    # sheet and not the glossary, a one-shot wants neither, and somebody who
    # letters from a script wants the words and no speaker guessed at all.
    story: bool = True
    learn_characters: bool = True
    learn_terms: bool = True
    name_speakers: bool = True
    honorifics: bool = True
    # Whether a reading may correct a box's kind between sfx and outside text.
    # OFF by default: it changes a thing the person may have set by hand, and
    # a setting that rewrites your own labels should be one you asked for.
    retype_kinds: bool = False
    medium: str = "manga"           # manga | manhwa | manhua | comic
    target: str = "en"              # en | es | pt | fr
    source: str = ""                # source language code; "" follows medium
    backend: str = "anthropic"      # anthropic | ollama | lmstudio | llamacpp | openai
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    # Gemini's four configurable safety thresholds. "" leaves Google's
    # defaults alone; "OFF" turns those four down as far as the API allows.
    # Google's core protections are not configurable and stay on either way.
    safety: str = ""
    # Which STEP is about to call a model, for the message a provider's
    # refusal turns into. Transient - it is set fresh on every step and means
    # nothing between runs - but it is DECLARED, because the whole context is
    # serialised into project.json by `Project._state` and read back with
    # `SeriesContext(**saved)`. Setting an undeclared attribute on this
    # dataclass wrote a key the constructor then refused, `load` raised,
    # `_load_or_scan` swallowed it and `rescan` saved an empty project over
    # the chapter. Caught by `test_your_own_text_box.py` within the hour;
    # see `Project.load`, which no longer trusts this file to be a shape it
    # understands.
    step_name: str = ""

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.__dict__, fh, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "SeriesContext":
        if not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as fh:
            return cls(**json.load(fh))


def build_payload(page: Page, ctx: SeriesContext,
                  chapter: list | None = None) -> dict:
    return _base_payload(page, ctx, chapter)


_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
#: A capital after one of these is the start of a sentence, not a name.
_SENT_END = ".!?…\"'“”\n"


def _bare(w: str) -> str:
    """`Lancaster's` -> `Lancaster`. A possessive is the same name."""
    return re.sub(r"['’]s$", "", w)


def names_in(texts) -> list[str]:
    """The proper names in some finished English, in the order they appear.

    A name is a word that is capitalised somewhere it is NOT starting a
    sentence. That one rule does the whole job and needs no list of stop
    words: "Still," and "There" and "The" are capitals the full stop put
    there, and every one of them appears lower-case elsewhere in any real
    page. Run over the whole of lee's chapter it returns exactly the fourteen
    proper nouns in it and nothing else - Calliope, Canyon, Chryses, Chrysos,
    Demarcus, Edel, House, Lancaster, Laszlo, Lord, Majesty, Phara, Tuberin.

    That Chryses AND Chrysos are both in that list is the bug this exists for:
    they are the same man, spelled two ways, four pages apart.

    Possessives are folded in - `Lancaster's` is not a fifteenth name.
    """
    if isinstance(texts, str):
        texts = [texts]
    mid, lower, order = set(), set(), []
    for t in texts:
        t = t or ""
        for m in _WORD.finditer(t):
            w = m.group(0)
            before = t[:m.start()].rstrip()
            starts = (not before) or before[-1] in _SENT_END
            if w[0].isupper():
                if not starts:
                    b = _bare(w)
                    if len(b) > 2 and b not in mid:
                        mid.add(b)
                        order.append(b)
            else:
                lower.add(_bare(w).lower())
    # A word that also turns up in lower case somewhere is an ordinary word
    # that happened to follow a colon or a dash, not a name.
    return [w for w in order if w.lower() not in lower]


def name_drift(used, fresh, close: float = 0.72) -> list:
    """Names in `fresh` that are near-misses of one already `used`.

    Chryses against Chrysos: same first letter, 0.86 alike, and never once in
    the same line. Two names that really are different - Edel and Ethel, if
    the story has both - turn up together on a page sooner or later, and a
    pair that has met is not drift.

    Returns `(was, now)` pairs. This never rewrites anything: two similar
    names CAN be two people, and a machine that quietly renamed somebody's
    character would be a worse fault than the one it was fixing.
    """
    out = []
    for now in fresh:
        if now in used:
            continue
        for was in used:
            if was[0].lower() != now[0].lower():
                continue
            if difflib.SequenceMatcher(None, was.lower(),
                                       now.lower()).ratio() >= close:
                out.append((was, now))
                break
    return out


def remember_said(ctx: "SeriesContext", page, adds: dict | None = None) -> None:
    """Note what this page called people and things, for the pages after it."""
    who = getattr(ctx, "speakers_seen", None)
    if who is None:
        who = ctx.speakers_seen = []
    low = {w.lower() for w in who}
    for r in page.ordered():
        n = (getattr(r, "speaker", "") or "").strip()
        if n and n.lower() not in low:
            low.add(n.lower())
            who.append(n)
    terms = getattr(ctx, "terms_seen", None)
    if terms is None:
        terms = ctx.terms_seen = {}
    for k, v in (adds or {}).items():
        k, v = str(k).strip(), str(v).strip()
        # First rendering wins, the same rule the glossary itself uses: a
        # second one is the drift this is here to stop.
        if k and v and k not in terms:
            terms[k] = v
    # ...and the proper names the finished English on this page used. Read off
    # the prose, because the prose is where they drifted: nobody proposes a
    # surname and no speaker label carries one.
    names = getattr(ctx, "names_seen", None)
    if names is None:
        names = ctx.names_seen = []
    for n in names_in([r.dst_text or "" for r in page.ordered()]):
        if n not in names:
            names.append(n)
    # ...and the SOUNDS, which nothing was carrying at all. See
    # `SeriesContext.sounds_seen` for what that cost on lee's chapter.
    #
    # First rendering wins, the same rule as `terms` above and for the same
    # reason: the second one IS the drift. It is a floor, not a ceiling - a
    # sound the model gives a new word to on page 22 is exactly the thing
    # this is here to stop, and it can only stop it by having gone first.
    sounds = getattr(ctx, "sounds_seen", None)
    if sounds is None:
        sounds = ctx.sounds_seen = {}
    for r in page.ordered():
        if _kinds.family_of(getattr(r, "kind", "") or "") != "sfx":
            continue
        k = sound_key(getattr(r, "src_text", ""))
        v = " ".join((getattr(r, "dst_text", "") or "").split())
        if k and v and k not in sounds:
            sounds[k] = v


def sound_key(s: str) -> str:
    """The comparison form of a drawn sound.

    Whitespace out - a sound drawn down a column arrives with newlines in it
    and `ザ\\nブン` is `ザブン` - and full width normalised, because `ﾄﾞﾝ` and
    `ドン` are one sound in two encodings.

    It does NOT fold katakana into hiragana, and that restraint is borrowed
    whole from `editor._fold_kana`, which learnt it the hard way: `キョロ` and
    `きょろ` are two spellings somebody may have chosen on purpose. Folding
    them here would be milder than folding them there - the worst it can do is
    hand one spelling the other's English - but it is the same wrong idea and
    the author's choice is not ours to flatten.
    """
    import unicodedata
    return unicodedata.normalize("NFKC", "".join((s or "").split()))


# Roughly how much area one character of typeset English takes, as a multiple
# of the type size squared. It was reasoned at 0.6 - half the size wide, 1.15
# of it tall with the leading - and then MEASURED, by putting sentences of
# growing length through `typeset._best` against the real balloon masks of a
# 71-page chapter and asking where it stopped fitting. The answer is 1.05: the
# reasoning left out the space between words, the ragged right of a wrapped
# line, and the fact that a balloon is a round hole so the top and bottom lines
# get a fraction of the width the middle ones do.
CHAR_AREA = 1.05
BALLOON_PACK = 0.55

# How far past the estimate a line has to go before it is worth saying so. The
# estimate is an estimate; a note on a line that is merely snug is a note
# nobody will read twice.
OVER_FITS = 1.25

# There was a `comfort_size` here - 0.7 of the project's full type size - and
# everything about length was measured against it: the budget in the payload,
# and the note. It is gone with the budget. lee: *"i wan the most accurate
# transaltion no matter the leght of the of it so i dont want to shrink or
# expand teh translation to fit anythng"*.
#
# Comfort was the right question while the model was being asked to cut words.
# It is the wrong question now: a line that comes out at small type is not a
# defect any more, it is the price of the accurate line, and 141 of the 220
# lines on lee's own chapter were over the comfortable size while NONE of them
# were over the floor. A report where two thirds of the flags are things
# nobody is going to act on is a report nobody reads.


def fits_chars(region, size: int = 12) -> int:
    """How many characters of English that balloon holds at `size`.

    Zero when there is nothing to measure - no mask and no box - and the
    caller leaves the number out rather than sending a guess.
    """
    px = 0
    m = getattr(region, "bubble_mask", None)
    if m is not None:
        try:
            px = int((m > 0).sum())
        except Exception:
            px = 0
    if not px:
        b = getattr(region, "bubble_bbox", None) or getattr(region, "bbox", None)
        if b and len(b) == 4:
            px = int(b[2]) * int(b[3])
    size = max(6, int(size or 12))
    n = int(px * BALLOON_PACK / (CHAR_AREA * size * size))
    return n if n >= 4 else 0


# A run is a run of MARKS, not of one mark: "?!!" is three.
_RUN = re.compile(r"[!?！？]{2,}")


def marks(t: str) -> int:
    """The longest run of ! or ? in a line. 0 when there is none."""
    return max((len(m.group(0)) for m in _RUN.finditer(t or "")), default=0)


def quieter(dst: str, src: str) -> str:
    """Did the line come back with its shout taken off?

    `이건 기적이야!!!` came back "This is a miracle!" and `아이고, 진우야아!!!`
    came back "Oh, Jinwoo...!". Four of those on one chapter, and all four
    arrived the same week the prompt started asking for shorter lines - asked
    to cut, the model cut punctuation, which is the one thing on the page that
    is not words. A run of marks is drawn at the size the artist drew it.

    A note and not a repair: adding the marks back would be writing the line,
    and the person reading the flag can see the page.
    """
    was, now = marks(src), marks(dst)
    if was >= 2 and now < was:
        return "the source shouts %d marks and this has %d" % (was, now)
    return ""


def too_long(dst: str, region, size: int = 12) -> str:
    """Will the balloon not hold this line AT ALL?

    `size` is the project's FLOOR - the smallest type it will set - and that is
    the whole of what changed here. It used to be `comfort_size`, so the note
    meant "this will come out small", and the model was being asked to cut
    words to avoid it. It is not asked that any more: lee wants the accurate
    line whatever it costs in type size, so small type is the answer and not a
    fault. What is still worth saying is that a line will not go in at any size
    the project allows, because that one the typesetter cannot solve.

    Only where there is a balloon to measure - see `fits_chars`, which is an
    estimate and is treated as one: the note is only raised at OVER_FITS past
    it, so a line that is merely snug says nothing.
    """
    room = fits_chars(region, size)
    n = len((dst or "").strip())
    if room and n > room * OVER_FITS:
        return "about %d characters for a balloon that holds ~%d" % (n, room)
    return ""


#: What a line is allowed to end on. Anything else, where the source trailed
#: off, is a sentence that stopped rather than one that faded.
_ENDED = tuple('.!?…‥—–-"\'”’」』）)】』～~')


def stops_short(dst: str, src: str) -> str:
    """The source trails off and the English just stops.

    lee's page 008: `とっても良かったですあり…` - she is saying thank you and is
    cut off - came back **"It was wonderful. Than"**. Not shortened, not
    mistranslated: it ends mid-word with nothing after it, and on the finished
    page that reads as a typo rather than as somebody being interrupted.

    A note and not a repair, the same as `quieter` above: adding the dots back
    would be choosing how the line breaks off, and the person reading the flag
    can see the page. "Than-" and "Thank yo-" and "Than..." are three different
    performances and only one of them is the typesetter's.
    """
    s, d = (src or "").strip(), (dst or "").strip()
    if not s or not d:
        return ""
    if not s.endswith(("…", "‥", "—", "―", "－", "...", "．．．")):
        return ""
    if d.endswith(_ENDED):
        return ""
    return "the source trails off and this stops dead: %r" % d[-24:]


# There was a `half_a_sound` here for a day, flagging any sound effect whose
# English began mid-word: lee's page 016 came back "Si..." in one box and
# "lence..." in the next, and I read that as the model cutting a word in half.
# He looked at the page and said it was right - *"everrything is working as
# entened the 2 016 and 017 are not mistakes"*. しん… IS one hush drawn across
# two boxes, and splitting the English where the drawing splits is the answer
# he wants. The check was calling a good page bad, so it is gone, along with
# the prompt rule that told the model not to do it.


def already_said(ctx: "SeriesContext") -> dict:
    """The speaker labels and the term renderings this chapter has used.

    One person, one name. A grandfather labelled "Jinwoo\'s Grandfather" on
    page 46 and "Osung Group Chairman" on page 57 is two characters as far as
    the sheet is concerned, and the sheet is what every later chapter starts
    from. Same for a term: `침식` came back "erosion" five times and "Erosion"
    twelve on one chapter, which is two terms.

    The character sheet and the glossary already travel with the request and
    are not enough on their own - a one-off speaker never reaches the sheet by
    design (a guard, a bystander), and a term nobody proposed never reaches
    the glossary. This is the rest of it: what was SAID, whether or not it was
    written down.

    `names` is the third of those gaps and the widest. A person NEVER goes in
    the glossary - the prompt forbids it, so that nobody is listed twice - and
    the glossary is the only place that binds a source spelling to an English
    one. So a character's romanisation is written down NOWHERE: the sheet
    holds "Laszlo" because that is the speaker label, and the surname in the
    narration was invented fresh on page 41 and invented again on page 45.
    This is the list of names the chapter's prose has actually used, which is
    the only record of that decision there has ever been.
    """
    out = {}
    who = [str(x).strip() for x in (getattr(ctx, "speakers_seen", None) or [])
           if str(x).strip()]
    seen, keep = set(), []
    for w in who:
        if w.lower() not in seen:
            seen.add(w.lower())
            keep.append(w)
    if keep:
        out["speakers"] = keep[:40]
    terms = {str(k): str(v) for k, v in
             (getattr(ctx, "terms_seen", None) or {}).items() if k and v}
    if terms:
        out["terms"] = dict(list(terms.items())[:60])
    # ...and the SOUNDS. The fourth gap and the one nothing covered at all: a
    # sound effect has no speaker, is never proposed as a term and never
    # reaches the glossary, so what a chapter decided `スッ` was had no record
    # anywhere. `SeriesContext.sounds_seen` has the measurement.
    #
    # Both directions matter and the prompt asks for both, which is why the
    # whole list travels rather than a lookup of the sounds on this page: one
    # Japanese sound must get one English word, AND two Japanese sounds the
    # artist drew differently must not collapse into the same one. The second
    # of those cannot be checked against a sound that is not in front of you.
    #
    # It is about 150 tokens on a chapter with fifty sound effects in it,
    # measured, and like the three lists above it is not in what
    # `editor.context_boxes` prices - `coins.drift` measures what a run really
    # sent against what the shape predicted and corrects for it, which is how
    # the other three have always been paid for.
    sounds = {str(k): str(v) for k, v in
              (getattr(ctx, "sounds_seen", None) or {}).items() if k and v}
    if sounds:
        out["sounds"] = dict(list(sounds.items())[:80])
    names = [str(x).strip() for x in (getattr(ctx, "names_seen", None) or [])
             if str(x).strip()]
    if names:
        # The most recent, not the first: a chapter long enough to overrun
        # this cap has moved on to a different cast, and the names that are
        # about to come round again are the ones just used.
        out["names"] = names[-60:]
    return out


def _base_payload(page: Page, ctx: SeriesContext,
                  chapter: list | None = None) -> dict:
    said = already_said(ctx)
    # KEY ORDER IS THE CACHE.
    #
    # Every provider's prompt cache works on a PREFIX: the longest run of bytes
    # from the start of the request that matches something it already has.
    # Google's is automatic and free above 1,024 tokens and asks only that the
    # repeated part come first; Anthropic's is marked and asks the same.
    #
    # Everything down to `glossary` is byte-identical on every page of a
    # chapter. Everything from `characters` on is not: the character sheet
    # grows as the chapter is read, the tail is the last page's last lines, and
    # the regions are this page. Putting one changing field in the middle ends
    # the prefix there and throws away every fixed byte after it - which is
    # what `characters` sitting above `previous_page_tail` used to do, and what
    # `keep_honorifics` sitting below them still did with a field that never
    # changes at all.
    #
    # So: fixed first, in a fixed order; then the ones that move. The model is
    # handed exactly the same information either way - a JSON object's key
    # order carries no meaning - but the cache can see where the repetition
    # stops.
    # What the story switches turn off. Named in the payload rather than
    # silently dropped, because the system prompt asks for these things by
    # name - a model told to propose `character_additions` and then quietly
    # ignored is a model spending output tokens on an answer nobody reads, and
    # output is the expensive side of the bill.
    #
    # It sits in the FIXED half: the switches do not change during a run, so
    # the bytes are identical on every page and the cache keeps them.
    story = getattr(ctx, "story", True)
    off = []
    if not story or not getattr(ctx, "learn_characters", True):
        off.append("character_additions")
    if not story or not getattr(ctx, "learn_terms", True):
        off.append("glossary_additions")
    if not getattr(ctx, "name_speakers", True):
        off.append("speaker")
    return {
        "medium": ctx.medium,
        "source_language": source_language(ctx.medium,
                                           getattr(ctx, "source", "")),
        "target_language": TARGETS.get(ctx.target, "English"),
        "keep_honorifics": ctx.honorifics,
        **({"do_not_return": off} if off else {}),
        **({"series_context": ctx.synopsis,
            "glossary": ctx.glossary} if story else {}),
        # The chapter belongs UP HERE, with the fixed things, even though it
        # is not fixed for ever - it is fixed for the RUN, which is what a
        # cache is measured over. It used to be appended after the regions,
        # which put four and a half thousand tokens just past the end of the
        # prefix and threw the saving away on every page of every run.
        **({"chapter_context": chapter} if chapter else {}),
        # ---- everything below here changes from page to page ----
        **({"characters": getattr(ctx, "characters", {}) or {}}
           if story else {}),
        "previous_page_tail": ctx.previous_page_tail[-6:],
        # What this chapter has already called things. Page to page and not
        # fixed, so it belongs down here below the cached prefix.
        **({"already_said": said} if said else {}),
        "regions": [
            {
                "id": r.id,
                "panel": r.panel_id,
                "kind": r.kind,
                "text": r.src_text,
                # NO LENGTH BUDGET TRAVELS WITH A REGION ANY MORE.
                #
                # There were two: `src_char_count`, which the prompt turned
                # into "aim under 1.6 times the source", and `fits_chars`,
                # how much the balloon holds at a comfortable size. Both are
                # gone, with the rule that used them. lee: *"i wan the most
                # accurate transaltion no matter the leght of the of it so i
                # dont want to shrink or expand teh translation to fit
                # anythng"*.
                #
                # Removing the RULE and leaving the NUMBERS would have been
                # the worse half of the job: a budget sitting in the payload
                # with nothing said about it is still a budget, and a model
                # that sees how much room it has will use it.
                #
                # `fits_chars` itself is alive and is what `too_long` measures
                # with - but at the floor now, not at a comfortable size, so
                # it says "this will not fit at all" rather than "this will be
                # small". See `too_long`.
                # Two different facts, and they used to be one key. See
                # `models.TextRegion.link_kind`.
                **({("balloon"
                     if getattr(r, "link_kind", "") == "balloon" else "link"):
                    int(r.link)} if getattr(r, "link", 0) else {}),
            }
            for r in page.ordered()
            if r.src_text.strip()
        ],
    }


def _repair_json(s: str) -> str:
    """Best-effort repair of the JSON mistakes models actually make.

    The recurring failures in the field: a double quote inside a translated
    line left unescaped ('Expecting , delimiter'), literal newlines inside
    strings, smart quotes used as delimiters, and trailing commas. Walk the
    text tracking whether we are inside a string and fix each in place.

    ...and the QUOTES AROUND A KEY, which is what took lee's chapter down. A
    reply that opens ``{"regions":[{"id":0,translation:"..."`` - the key left
    bare, or wrapped in single quotes - fails with *Expecting property name
    enclosed in double quotes: line 1 column 21 (char 20)*, and that is his
    error to the character. Two repairs, and the difference between them is
    the point:

    * **A single quote outside a string is a string delimiter.** Anywhere it
      appears, key or value: ``'translation'`` and ``'네, 스승님.'`` are the
      same slip and there is nothing to lose by fixing both.
    * **A bareword is only quoted when a COLON follows it** - i.e. only where
      it can be a key. A bareword anywhere else is `null`, `true`, or a
      number, and every reply is full of those; quoting them would turn
      ``"speaker":null`` into the string "null" on every page in the chapter.
      A bareword that is a genuine mistake stays a mistake, and the reply is
      asked for again, which is the better answer than believing it.
    """
    out: list[str] = []
    i, n, in_str = 0, len(s), False
    while i < n:
        c = s[i]
        if not in_str:
            if c == "'":
                j = s.find("'", i + 1)
                if j != -1:
                    out.append('"' + s[i + 1:j].replace('"', '\\"') + '"')
                    i = j + 1
                    continue
            elif c not in "\"“”" and (c.isalnum() or c == "_"):
                j = i
                while j < n and (s[j].isalnum() or s[j] in "_-."):
                    j += 1
                k = j
                while k < n and s[k] in " \t\r\n":
                    k += 1
                if k < n and s[k] == ":":
                    out.append('"' + s[i:j] + '"')
                    i = j
                    continue
            if c == '"' or c in "“”":
                in_str = True
                out.append('"')
            else:
                out.append(c)
        else:
            if c == "\\":
                out.append(c)
                if i + 1 < n:
                    out.append(s[i + 1])
                    i += 1
            elif c == "\n":
                out.append("\\n")
            elif c == "\r":
                pass
            elif c == "\t":
                out.append("\\t")
            elif c == '"' or c in "“”":
                j = i + 1
                while j < n and s[j] in " \t\r\n":
                    j += 1
                if j >= n or s[j] in ",:}]":
                    out.append('"')          # a real string terminator
                    in_str = False
                else:
                    out.append('\\"')        # a quote the model forgot to escape
            else:
                out.append(c)
        i += 1
    t = "".join(out)
    return re.sub(r",\s*([}\]])", r"\1", t)   # trailing commas


def _looks_truncated(s: str) -> bool:
    """A reply that ran out of tokens mid-object."""
    depth = 0
    in_str = esc = False
    for c in s:
        if esc:
            esc = False
            continue
        if in_str:
            if c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
    return depth > 0 or in_str


def _extract_json(s: str) -> dict:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.M).strip()
    # cut prose away: keep from the first '{' to its balanced close
    start = s.find("{")
    if start != -1:
        depth = 0
        in_str = esc = False
        end = -1
        for k in range(start, len(s)):
            c = s[k]
            if esc:
                esc = False
                continue
            if in_str:
                if c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = k
                    break
        s = s[start:end + 1] if end != -1 else s[start:]
    try:
        return json.loads(s, strict=False)
    except json.JSONDecodeError:
        return json.loads(_repair_json(s), strict=False)


def list_models(base_url: str, api_key: str = "", timeout: int = 20) -> list:
    """The model names this key can actually use, straight from the provider.

    Every OpenAI-shaped server answers `GET /models`, including Gemini's
    compatibility endpoint, OpenRouter, Groq and Ollama. Returns [] rather than
    raising: this is only ever used to HELP - to fill the suggestion list under
    the model box, and to say something useful when a name turns out to be
    wrong. A provider that will not answer must not take the page down with it.
    """
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(
            base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {api_key or 'not-needed'}"})
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            data = json.loads(fh.read())
    except Exception:
        return []
    out = []
    for m in (data.get("data") or data.get("models") or []):
        name = m.get("id") or m.get("name") if isinstance(m, dict) else m
        if not name:
            continue
        # Gemini answers "models/gemini-3.5-flash"; the chat endpoint takes
        # either, but the short form is what a person recognises. ONLY that
        # prefix comes off: OpenRouter names a model by who makes it, and
        # cutting at the last slash turned `anthropic/claude-sonnet-5` into
        # `claude-sonnet-5` - a name OpenRouter has never heard of, offered in
        # a menu, chosen, and 404 one call later.
        name = str(name)
        out.append(name[len("models/"):] if name.startswith("models/") else name)
    return sorted(set(out))


# Providers retire models. Google's answer when it happens is a 404 whose body
# begins with the JSON of an error object - accurate, and unreadable in a red
# bar halfway down the editor.
#   lee: *"RuntimeError: OCR server returned 404: [{ "error": { "code": 404,
#   "message": "This model models/gemini-2.5-flash-lite is no longer available
#   to new users..."*
# So a wrong model name is named as such, and answered with the names that DO
# work on this key - the one thing the person needs and cannot look up from
# inside the app.
_GONE = ("no longer available", "not found", "does not exist",
         "is not supported", "unknown model", "invalid model",
         "decommissioned", "deprecated")


_BAD_KEY = ("api key", "api_key", "unauthorized", "invalid authentication",
            "incorrect api key", "permission denied")


def _model_error(what: str, model: str, code: int, body: str,
                 base_url: str, api_key: str) -> str:
    low = body.lower()
    # A refused key first: it looks like a model problem in the raw JSON, and
    # sending somebody to change the model name when the model name is right is
    # the worst answer of the three.
    # lee: *"OCR server returned 400 ... Please pass a valid API key"*.
    if code in (400, 401, 403) and any(w in low for w in _BAD_KEY):
        got = (api_key or "").strip()
        note = ("no key is set for it" if not got
                else f"the key it has ends {got[-4:]}")
        return (f"the {what} step's key was refused by the provider "
                f"(HTTP {code}) — {note}. Paste it again in Settings → "
                f"AI models; a key copied with a space or a newline "
                f"on the end fails exactly like a wrong one, and so does the "
                f"word \"set\", which is what the screen shows INSTEAD of a "
                f"saved key and is never a key itself.")
    if code not in (400, 403, 404) or not any(w in low for w in _GONE):
        return f"{what} server returned {code}: {body[:200]}"
    have = [m for m in list_models(base_url, api_key) if "embed" not in m]
    msg = (f'the {what} step asked for a model called "{model}", and the '
           f"provider says there is no such model on this key (HTTP {code}).")
    if have:
        show = ", ".join(have[:8])
        more = f" …and {len(have) - 8} more" if len(have) > 8 else ""
        msg += (f" Change it in Settings → AI models. This key can "
                f"use: {show}{more}.")
    else:
        msg += " Change it in Settings → AI models."
    return msg


# ------------------------------------------------------ no content filter
#
# lee: *"no ai shoud have any content filter"*. There is no switch for this in
# Settings and no default to argue about: every request that CAN carry a
# filter-off goes out with one.
#
# Where that switch exists is Google's - four categories whose threshold you
# choose, set per request on your own key. `OFF` is one of the documented
# values and is what "turn the filters off" means here. It travels to Google's
# own endpoint and through OpenRouter (see `takes_google_options`).
#
# The other two makers the app can reach publish no equivalent. Claude and
# OpenAI have no per-request threshold at all - their filtering is inside the
# model and inside their serving stack, and no field on the wire moves it - so
# for those there is nothing being left on; there is nothing to send. A local
# llama.cpp has no filter in the first place.
#
# And what the Google switch does NOT do - cannot, at any threshold - is
# disable Google's built-in protections against core harms such as child
# safety. Those are not configurable and stay on. So a page can still come back
# refused; that is why `_refusal` below exists, to say so plainly instead of
# failing on a schema error two retries later.
GEMINI_HARMS = ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT")


def is_google_endpoint(url: str) -> bool:
    low = (url or "").lower()
    # ...or the project's relay standing in front of it, which forwards the
    # request unchanged, safety settings included (`editor.relay_url`).
    return "generativelanguage.googleapis.com" in low or "/relay/gemini" in low


def _openrouter_body_extras(base_url: str, model: str) -> dict:
    """The two OpenRouter-only fields a request carries (task #119).

    `usage: {include: true}` asks for USAGE ACCOUNTING: the reply then
    carries `usage.cost` - what OpenRouter actually charged for the call -
    and `completion_tokens_details.reasoning_tokens`. `coins.usage_extras`
    reads both, so the bill settles on the provider's own number instead of
    our copy of their price table.

    `provider.max_price` is a routing ceiling, in USD PER MILLION tokens
    (their stated unit): any endpoint above it is skipped. Set at 1.5x our
    own table for the model, it lets routing pick any sane provider while
    refusing the one having an expensive day - which is what keeps the
    metered cost inside the hold the run was started on. A model our table
    does not price gets no ceiling: guessing one could route every request
    away.
    """
    if not is_openrouter_endpoint(base_url):
        return {}
    out = {"usage": {"include": True}}
    try:
        from . import coins as _c
        r = _c.rate_for(model, "openrouter")
        if r is not None and r is not _c.UNKNOWN and (r.inp or r.out):
            out["provider"] = {"max_price": {
                "prompt": round(r.inp * 1.5, 4),
                "completion": round(r.out * 1.5, 4)}}
    except Exception:
        pass
    return out


def is_openrouter_endpoint(url: str) -> bool:
    low = (url or "").lower()
    return "openrouter.ai" in low or "/relay/openrouter" in low


def takes_google_options(url: str, model: str = "") -> bool:
    """Will this request reach an endpoint that accepts these options?

    lee: *"all the trherolod for all the ais shiud bre off"*, and then plainer:
    *"no ai shoud have any content filter is what i meant"*. So the rule is not
    "Google gets its filters turned down" - it is "wherever a filter can be
    turned off, it is off", and this answers where the switch exists.

    Google's own endpoint, obviously. And EVERY model through OpenRouter, not
    only `google/…`: OpenRouter forwards provider-specific fields to the
    provider that recognises them and drops them for the rest, so the block
    costs nothing on a Claude route and still lands when the model string is an
    alias, an `auto` route, or a Gemini reached under some other name. Gating on
    the `google/` prefix meant the crossing `editor.or_openrouter` makes - the
    moment a key is missing or refused - could quietly put the filters back on,
    on the run that had already gone wrong once.

    Everything else is not a "no": it is that there is nothing to send. Claude
    and OpenAI publish no per-request threshold - their filtering is in the
    model and in their own serving stack, with no knob on the wire - and a local
    llama.cpp has no filter to begin with. If some endpoint turns out to take
    one, the sticky `_no_safety` retry below is what makes trying it cheap.
    """
    return is_google_endpoint(url) or is_openrouter_endpoint(url)


def safety_body(threshold: str = "OFF") -> dict:
    """The `extra_body` the OpenAI-compatible endpoint carries Gemini's own
    options in. Documented shape: extra_body -> google -> safety_settings."""
    return {"google": {"safety_settings": [
        {"category": c, "threshold": threshold} for c in GEMINI_HARMS]}}


# What a refused answer looks like coming back through the OpenAI-compatible
# endpoint: a choice with no content and a finish reason that says why.
_REFUSED = ("content_filter", "safety", "blocked", "prohibited_content",
            "recitation", "image_safety")


def _refusal(data: dict) -> str:
    """"" when the reply is a real answer, or a sentence naming the refusal.

    Before this, a refused page came back with an empty message, failed the
    schema check, was retried twice, and then reported something about missing
    regions - which is true and tells you nothing. Refusals are not errors in
    the code; they are an answer, and they should read like one.
    """
    try:
        ch = (data.get("choices") or [{}])[0]
    except (AttributeError, IndexError):
        return ""
    reason = str(ch.get("finish_reason") or ch.get("native_finish_reason")
                 or "").lower()
    text = ((ch.get("message") or {}).get("content") or "")
    if text.strip():
        return ""
    fb = data.get("prompt_feedback") or data.get("promptFeedback") or {}
    blocked = str(fb.get("block_reason") or fb.get("blockReason") or "").lower()
    if not any(k in reason for k in _REFUSED) and not blocked:
        return ""
    why = blocked or reason or "safety"
    return ("the model refused this page (%s) and sent nothing back. "
            "Google's protections against core harms cannot be switched off, "
            "so a page can still be refused with the thresholds turned down. "
            "Run this page with a different model, or typeset it by hand."
            % why)


# How many times a request that simply did not come back in time is sent
# again. Separate from the rate-limit budget on purpose: a 429 comes back in
# milliseconds and costs nothing to retry, while each of these costs a whole
# `timeout` of waiting, so six of them is half an hour of somebody watching a
# progress bar that is not moving.
SLOW_TRIES = 3

# What counts as "the answer did not arrive", as opposed to "the answer was
# no". None of these is a refusal, a bad request or a wrong key: the request
# was accepted and the connection then went quiet or went away. This is the
# most retryable class of failure there is, and it was the one thing the loop
# below did not retry - a read timeout on page 12 of a 23-page proofread ended
# the whole run with a stack trace out of `ssl.py`.
# ...and a BROKEN one. `ssl.SSLError` is the connection itself failing, not
# the server answering: `SSLV3_ALERT_BAD_RECORD_MAC` is one record arriving
# with the wrong integrity tag, `UNEXPECTED_EOF_WHILE_READING` is the far end
# vanishing mid-record. Neither says anything about the request, and sending
# the request again is the whole of the fix. lee's Read text died at page 22
# of 58 on a bad record MAC - a run that had already paid for the pages it
# never got to, killed by one corrupted packet on a link that then worked
# fine for the retry that never happened.
#
# It belongs HERE rather than in its own branch because the class is the same
# one this tuple already names: accepted, then nothing usable came back.
# Uploading a page image is a megabyte-plus POST, which is exactly the shape
# of request an antivirus TLS proxy or a tired VPN mangles.
_WENT_QUIET = (TimeoutError, ConnectionError, http.client.HTTPException,
               ssl.SSLError)

# The one SSL failure that is an ANSWER and not an accident. A certificate
# that does not verify will not verify on the third try either, and retrying
# it hides the one thing the person has to fix. Same reason a name that does
# not resolve is not retried.
_NOT_QUIET = (ssl.SSLCertVerificationError,)


def _too_slow(what: str, model: str, seconds: int, tries: int, e=None) -> str:
    """The sentence a person gets instead of a traceback."""
    if isinstance(e, ssl.SSLError) or isinstance(
            getattr(e, "reason", None), ssl.SSLError):
        # A different failure needs a different sentence. "did not answer
        # within 300 seconds" sends somebody to look for a faster model, and
        # the wait had nothing to do with it: the answer was coming and the
        # link mangled it. What they can act on is the middle of the link.
        return (f"the secure connection to the {what} server broke {tries} "
                f"times running, so the {what} stopped here. This is not the "
                f"model, the key or the page - the request went out and the "
                f"reply came back damaged, which is what a VPN, a company "
                f"proxy or an antivirus that inspects traffic does to a big "
                f"upload. Everything finished before this is saved and the "
                f"pages it did not reach have been refunded. Run it again; "
                f"if it keeps stopping in the same place, turn off HTTPS "
                f"scanning for this app or run it off the VPN.")
    return (f"{model} did not answer within {seconds} seconds, {tries} times "
            f"running, so the {what} stopped here. Nothing is wrong with the "
            f"page - the request was accepted and the answer never came. "
            f"Everything finished before this is saved and the pages it did "
            f"not reach have been refunded. Run it again; if it keeps "
            f"happening, put a faster model on this step.")


def _went_quiet(e) -> bool:
    """...including a timeout wrapped in a URLError, which is what a slow
    CONNECT looks like while a slow READ raises the bare thing."""
    if isinstance(e, _NOT_QUIET):
        return False
    if isinstance(e, _WENT_QUIET):
        return True
    reason = getattr(e, "reason", None)
    return (reason is not None and isinstance(reason, _WENT_QUIET)
            and not isinstance(reason, _NOT_QUIET))


class OpenAICompatClient:
    """Minimal client for any OpenAI-compatible /chat/completions endpoint.

    Deliberately stdlib-only: the point of the local route is to avoid pulling
    in more dependencies, and the request shape is three fields.
    """

    def __init__(self, base_url: str, model: str, api_key: str = "",
                 timeout: int = 300, safety: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or "not-needed"
        self.timeout = timeout
        # "OFF"/"BLOCK_NONE"/… is sent as the threshold for the four
        # configurable categories, on every endpoint that has them. "" is not a
        # choice anybody makes any more - it is what an endpoint with no such
        # switch gets, because there is nothing to send it.
        self.safety = safety if takes_google_options(
            self.base_url, self.model) else ""
        # Which STEP is holding this client, for the error message. It used
        # to say "the OCR step's key was refused" whatever had actually
        # called, so a refusal on Translate sent lee to look at Read text's
        # settings. lee: *"the OCR step's key was refused"* -- when it wasn't.
        # `make_client` fills it in from `ctx.step_name`, which `editor.
        # _ctx_from_settings` sets from `STEP_LABEL`.
        self.step_name = ""

    def complete(self, system: str, user: str, max_tokens: int = 8000,
                 temperature: float = 0.25) -> str:
        """Free tiers rate-limit aggressively, so back off and retry on 429
        rather than failing the page. JSON mode is requested when the server
        supports it and quietly dropped when it does not - the same request
        works against OpenAI, Gemini, Groq, Ollama and llama.cpp."""
        import time
        import urllib.error
        import urllib.request

        delay = 3.0
        slow = 0
        for attempt in range(6):
            body_obj = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
            }
            if not getattr(self, "_no_or_extras", False):
                body_obj.update(_openrouter_body_extras(self.base_url,
                                                        self.model))
            if self.safety and not getattr(self, "_no_safety", False):
                body_obj["extra_body"] = safety_body(self.safety)
            if not getattr(self, "_no_temperature", False):
                body_obj["temperature"] = temperature
            if not getattr(self, "_no_json_mode", False):
                body_obj["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(body_obj).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.api_key}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as fh:
                    data = json.loads(fh.read())
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                low = body.lower()
                # a server that rejects one of the optional knobs gets the
                # same request again without it, immediately
                if e.code == 400 and "response_format" in low \
                        and not getattr(self, "_no_json_mode", False):
                    self._no_json_mode = True
                    continue
                if e.code == 400 and "temperature" in low \
                        and not getattr(self, "_no_temperature", False):
                    self._no_temperature = True
                    continue
                # A price ceiling that filtered every provider (a stale
                # table, a price rise) must not fail the page: the same
                # request goes again without the ceiling, and the settle
                # still catches whatever it really cost.
                if e.code in (400, 404) and not getattr(
                        self, "_no_or_extras", False) and (
                        "max_price" in low or "provider" in low):
                    self._no_or_extras = True
                    continue
                # an endpoint that will not take the safety block gets the
                # same request again without it rather than failing the page
                if e.code == 400 and ("safety" in low or "extra_body" in low) \
                        and not getattr(self, "_no_safety", False):
                    self._no_safety = True
                    continue
                if e.code in (429, 500, 502, 503, 529) and attempt < 5:
                    wait = float(e.headers.get("retry-after") or delay)
                    time.sleep(min(wait, 60))
                    delay *= 2
                    continue
                raise RuntimeError(_model_error(
                    # The step that is actually running, not the one this
                    # method is usually used for. This said "translation" and
                    # the vision one said "OCR", so a refusal on Proofread
                    # named whichever method it happened to come through.
                    self.step_name or "translation", self.model, e.code, body,
                    self.base_url, self.api_key)) from e
            except Exception as e:
                # A request that went quiet is sent again. Separate from the
                # branch above because the two are different failures: a 429 is
                # the server saying no, and this is it saying nothing at all.
                if _went_quiet(e):
                    slow += 1
                    if slow < SLOW_TRIES:
                        time.sleep(min(delay, 20))
                        delay *= 2
                        continue
                    raise RuntimeError(_too_slow(
                        "translation", self.model, self.timeout, slow, e)) from e
                if isinstance(e, urllib.error.URLError):
                    raise RuntimeError(
                        f"could not reach the translation server at "
                        f"{self.base_url} ({e}). Is it running?") from e
                raise
        else:
            raise RuntimeError("translation server kept rate-limiting us")

        _meter(data, self.model)
        why = _refusal(data)
        if why:
            raise RuntimeError(why)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(
                f"unexpected reply from the translation server: "
                f"{json.dumps(data)[:200]}") from e

    def complete_vision(self, system: str, user: str, image_b64: str,
                        media_type: str = "image/png",
                        max_tokens: int = 4000) -> str:
        """Same as complete(), but the user turn carries a page image - for the
        vision OCR reader. OpenAI/Gemini both take an image_url data URL."""
        import time
        import urllib.error
        import urllib.request
        content = [
            {"type": "text", "text": user},
            {"type": "image_url",
             "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
        ]
        delay = 3.0
        slow = 0
        for attempt in range(6):
            body_obj = {"model": self.model, "max_tokens": max_tokens,
                        "messages": [{"role": "system", "content": system},
                                     {"role": "user", "content": content}]}
            if not getattr(self, "_no_or_extras", False):
                body_obj.update(_openrouter_body_extras(self.base_url,
                                                        self.model))
            if self.safety and not getattr(self, "_no_safety", False):
                body_obj["extra_body"] = safety_body(self.safety)
            if not getattr(self, "_no_json_mode", False):
                body_obj["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(body_obj).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.api_key}"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as fh:
                    data = json.loads(fh.read())
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                low = body.lower()
                if e.code == 400 and "response_format" in low \
                        and not getattr(self, "_no_json_mode", False):
                    self._no_json_mode = True
                    continue
                if e.code in (400, 404) and not getattr(
                        self, "_no_or_extras", False) and (
                        "max_price" in low or "provider" in low):
                    self._no_or_extras = True
                    continue
                if e.code == 400 and ("safety" in low or "extra_body" in low) \
                        and not getattr(self, "_no_safety", False):
                    self._no_safety = True
                    continue
                if e.code in (429, 500, 502, 503, 529) and attempt < 5:
                    time.sleep(min(float(e.headers.get("retry-after") or delay), 60))
                    delay *= 2
                    continue
                raise RuntimeError(_model_error(
                    self.step_name or "OCR", self.model, e.code, body,
                    self.base_url, self.api_key)) from e
            except Exception as e:
                if _went_quiet(e):
                    slow += 1
                    if slow < SLOW_TRIES:
                        time.sleep(min(delay, 20))
                        delay *= 2
                        continue
                    raise RuntimeError(_too_slow(
                        "reading", self.model, self.timeout, slow, e)) from e
                if isinstance(e, urllib.error.URLError):
                    raise RuntimeError(
                        f"could not reach the OCR server at {self.base_url} "
                        f"({e}).") from e
                raise
        else:
            raise RuntimeError("OCR server kept rate-limiting us")
        _meter(data, self.model)
        why = _refusal(data)
        if why:
            raise RuntimeError(why)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"unexpected OCR reply: {json.dumps(data)[:200]}") from e


def make_client(backend: str = "anthropic", base_url: str = "",
                model: str = "", api_key: str = "", safety: str = "",
                step_name: str = ""):
    """Return (client, model, kind).

    `step_name` is only ever read by the error message - see `_model_error`.
    It is passed rather than looked up because the client does not know what
    is holding it, and a refusal that names the wrong step sends somebody to
    fix settings that were never the problem.
    """
    if backend in LOCAL_PRESETS or backend == "openai":
        preset = LOCAL_PRESETS.get(backend, {})
        url = base_url or preset.get("base_url", "https://api.openai.com/v1")
        mdl = model or preset.get("model", "gpt-4o-mini")
        cl = OpenAICompatClient(url, mdl, api_key, safety=safety)
        cl.step_name = step_name or ""
        return cl, mdl, "openai"
    import anthropic
    # The key from Settings, not only the environment: `Anthropic()` bare
    # reads ANTHROPIC_API_KEY and nothing else, so the key typed into the
    # editor never reached a native Claude call.
    # `base_url` for Claude is the project's relay (`editor.relay_url`), which
    # speaks Anthropic's own shape: the SDK posts /v1/messages under it.
    return (anthropic.Anthropic(api_key=api_key or None, base_url=base_url or None),
            (model or MODEL), "anthropic")


# Models that refused the temperature knob ("`temperature` is deprecated for
# this model") - remembered so every following page skips it first try.
_NO_TEMPERATURE: set[str] = set()


# Anthropic's prompt cache has to be asked for, one block at a time, and it
# only pays above 1,024 tokens. The system prompt of a step is the same bytes
# on every page of every chapter, so it is exactly what a cache is for: written
# once and read for the rest of the run at a tenth of the price.
#
# Under the minimum it is not marked - a cache write costs MORE than a plain
# read, so marking a short prompt is a small loss on every page rather than a
# saving. That is why the reader's 442-token system prompt is left alone and
# the translator's 2,010 is not.
#
# Google's cache needs no marking at all: it is implicit, automatic and free
# above the same sort of threshold, and asks only that the repeated bytes come
# FIRST - which is what the key order in `_base_payload` is about.
CACHE_MIN_TOKENS = 1024


# The first key of the part that changes from page to page. Everything before
# it in the serialised payload is identical on every page of a run, which is
# what a cache is measured over.
FIRST_MOVING_KEY = "characters"


def split_at_the_fixed_part(user: str) -> tuple:
    """The serialised payload, cut where the repeated half ends.

    Anthropic caches what is MARKED, and only whole content blocks can be
    marked - so to have the synopsis, the glossary and the chapter context
    read at a tenth of the price, they have to be a block of their own with
    everything that moves in a second block after it.

    Cutting a JSON document in half sounds worse than it is: the model is
    handed the blocks joined back together, so what it reads is exactly the
    string that went in. Only the billing sees the seam.

    Returns ("", user) when the marker is not there, which is the safe answer:
    one block, nothing marked, no saving and no damage.
    """
    at = user.find('"%s":' % FIRST_MOVING_KEY)
    if at < 0:
        return "", user
    # Back up over the whitespace that belongs to the key, so the cut lands
    # between lines rather than inside one.
    while at > 0 and user[at - 1] in ' \t':
        at -= 1
    return user[:at], user[at:]


def _cacheable(system: str) -> bool:
    """Roughly, is this long enough to be worth caching? Four characters to a
    token is the usual English rule and this only has to clear a threshold."""
    return len(system or "") >= CACHE_MIN_TOKENS * 4


def _system_blocks(system: str):
    """The system prompt, marked for the cache when it is long enough."""
    if not _cacheable(system):
        return system
    return [{"type": "text", "text": system,
             "cache_control": {"type": "ephemeral"}}]


def _meter(resp, model: str = "") -> None:
    """Tell the coin meter what this call really used.

    Every AI step in the app goes through `_ask`, `_ask_vision` or the
    OpenAI-compatible client below, so these are the only four places a token
    is ever bought - which is why the charging lives here rather than being
    counted again, differently, in each step.

    It can never fail a page. A metering bug that loses a charge costs money;
    a metering bug that raises loses the translation, and the translation is
    the thing the person came for.
    """
    try:
        from . import coins
        coins.meter(resp, model)
    except Exception:
        pass


def _ask(client, kind: str, model: str, system: str, user: str,
         cache_prefix: str = "", max_tokens: int = 8000) -> str:
    """One turn. `cache_prefix` is the head of `user` that repeats across a
    run and is worth marking for the cache.

    `max_tokens` bounds the reply - callers that know the page pass
    `coins.reply_cap` (about twice the predicted reply), so the unbounded
    half of the bill is a number we chose. A retry after a truncated reply
    must pass the full 8000 rather than the cap that truncated it.

    Google needs no marking - its cache is implicit above about a thousand
    tokens and asks only that the repeated part come first, which is what the
    payload's key order is for. Anthropic caches only what is marked, hence
    this.
    """
    if kind == "openai":
        # No marking to do: the OpenAI-compatible path covers local models and
        # third-party gateways, and `user` already carries the whole payload.
        return client.complete(system, user, max_tokens=max_tokens)
    content = user
    if cache_prefix and _cacheable(cache_prefix):
        content = [
            {"type": "text", "text": cache_prefix,
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": user[len(cache_prefix):]},
        ]
    kwargs = dict(model=model, max_tokens=int(max_tokens or 8000),
                  system=_system_blocks(system),
                  messages=[{"role": "user", "content": content}])
    if model not in _NO_TEMPERATURE:
        try:
            resp = client.messages.create(temperature=0.25, **kwargs)
            _meter(resp, model)
            return "".join(b.text for b in resp.content if b.type == "text")
        except Exception as e:
            # Newer Anthropic models reject the parameter outright. Anything
            # else is a real error and must surface.
            if "temperature" not in str(e).lower():
                raise
            _NO_TEMPERATURE.add(model)
    resp = client.messages.create(**kwargs)
    _meter(resp, model)
    return "".join(b.text for b in resp.content if b.type == "text")


def _ask_vision(client, kind: str, model: str, system: str, user: str,
                image_b64, media_type: str = "image/png") -> str:
    """One vision turn: system + (image(s), user text) -> model reply.

    `image_b64` is one image or a list of them. Several go in one turn because
    a page read as one crop per box is a dozen small pictures that all want the
    same system prompt and the same page listing - sending them one at a time
    would multiply that text by a dozen and spend the whole saving.
    """
    imgs = [image_b64] if isinstance(image_b64, str) else list(image_b64)
    if kind == "openai":
        # The OpenAI-shaped client takes one image. Several is an Anthropic
        # path only, and `read_page_ocr` does not batch when it is not.
        return client.complete_vision(system, user, imgs[0], media_type)
    content = [{"type": "image", "source": {"type": "base64",
                "media_type": media_type, "data": b}} for b in imgs]
    content.append({"type": "text", "text": user})
    kwargs = dict(model=model, max_tokens=4000, system=_system_blocks(system),
                  messages=[{"role": "user", "content": content}])
    resp = _create_read(client, model, kwargs)
    _meter(resp, model)
    return "".join(b.text for b in resp.content if b.type == "text")


# Models that refused to have their thinking turned off - remembered, like
# `_NO_TEMPERATURE`, so every following page skips the attempt. Fable 5 and
# the Mythos line reject `thinking: {"type": "disabled"}` outright, and Opus 5
# rejects it above effort `high`; either way the read goes ahead with thinking
# on, is metered for what it really used, and is quoted high rather than low.
_NO_THINKING_OFF: set[str] = set()


def _create_read(client, model: str, kwargs: dict):
    """One Anthropic read, with the two knobs a read asks for and a model may
    refuse: temperature 0 and thinking off.

    Temperature 0 is the flattest, most literal decoding there is, and it
    suppresses the "plausible but not in the picture" guesses. Newer models
    reject the parameter outright.

    Thinking off is task #125 by lee's decision - *"turn it of ad let me do a
    run and compare"* - for the models on `coins.READ_THINKING_OFF`, which is
    also the list the quote reads, so the price and the request agree. On
    Claude 5 thinking is on unless asked otherwise, and on lee's 58-page
    manhwa five sixths of the read's output was reasoning nobody saw and
    nobody had asked for.

    Each knob is dropped on its own when the model refuses it, and the
    refusal is remembered for the process. Anything else is a real error and
    must surface.
    """
    from . import coins as _c
    want_temp = model not in _NO_TEMPERATURE
    want_off = _c.read_thinks_off(model) and model not in _NO_THINKING_OFF
    for _ in range(3):
        extra = {}
        if want_temp:
            extra["temperature"] = 0
        if want_off:
            extra["thinking"] = {"type": "disabled"}
        try:
            return client.messages.create(**extra, **kwargs)
        except Exception as e:
            said = str(e).lower()
            if want_temp and "temperature" in said:
                _NO_TEMPERATURE.add(model)
                want_temp = False
                continue
            if want_off and ("thinking" in said or "effort" in said):
                _NO_THINKING_OFF.add(model)
                want_off = False
                # Out loud, once: the read that follows costs what a thinking
                # read costs, and the person comparing the two must know
                # which one they got.
                print(f"[read] {model} would not turn its thinking off "
                      f"({e}); reading with it on", flush=True)
                continue
            raise
    return client.messages.create(**kwargs)


def build_ocr_system(source: str = "Japanese") -> str:
    return (
        f"You are a meticulous OCR transcriber for {source} comics. You are "
        "shown ONE image: either a whole page, or a piece of one cut out at "
        "higher resolution. Regions you must transcribe are outlined in RED and "
        "labelled with a red number tag. Anything outlined in GREY belongs to a "
        "different part of the page — ignore its text completely.\n\n"
        "An outline follows the SHAPE of the words it holds, so a line of text "
        "drawn at an angle has a slanted outline. Read only the text the "
        "outline goes round — not everything in the upright rectangle it would "
        "fit inside. Where two outlines cross, each one's words are the ones it "
        "actually encloses — and where a line of text falls inside more than "
        "one outline, it belongs to the outline that fits it most closely, not "
        "to the larger one it happens to sit in.\n\n"
        "Transcribe the EXACT text printed inside each numbered region:\n"
        f"- Copy the {source} characters exactly as printed, in reading order "
        "(for Japanese: top-to-bottom, and right-to-left across columns).\n"
        "- Output the ORIGINAL script only. Do NOT translate. Do NOT romanize.\n"
        # The rule was already here and was ignored on lee's page 013, so it now
        # carries the failure itself. Naming the exact confusion beats naming
        # the category: `実` with じつ set beside it came back `実じっは…`, the
        # ruby spliced into the middle of the word it explains.
        "- Do NOT include furigana / ruby (the tiny pronunciation kana printed "
        "beside kanji). Transcribe the main line only. The ruby is set SMALLER "
        "and OFF TO THE SIDE of the character it belongs to; it is never part "
        "of the line. If 実 has じつ printed beside it, the line is 実は… and "
        "NOT 実じっは… — a run of kana appearing in the middle of a word it "
        "spells out is ruby that has been read by mistake.\n"
        "- Transcribe ONLY what is actually printed. Never guess, complete, or "
        "invent text. If a region is unreadable, decorative, or empty, return "
        "an empty string for it. A plausible-sounding line that is not clearly "
        "in the image is WRONG — prefer the empty string.\n"
        # Directional, because the failures all go ONE way: the small form is
        # written full-size, never the reverse. Five in 220 lines of lee's
        # chapter - タツ for タッ, クツ for クッ, ぶつ for ぶっ, あつて for
        # あって, ヘフ？ for へっ？ - and each one changes the English: クツ
        # was translated "PFFT".
        "- Preserve small kana (っ ッ ゃ ゅ ょ ァ ィ) vs full kana, and dakuten "
        "/ handakuten exactly (が vs か, で vs て, ば vs は). THE SMALL FORM IS "
        "THE ONE THAT GETS MISSED: a sound ending in ツ is almost always ッ "
        "(タッ, クッ, not タツ, クツ), つ before て/た/と is almost always っ "
        "(あって, not あつて), and a sound that ends in つ is almost always っ "
        "(ぶっ, not ぶつ). Look at the character's SIZE against the ones around "
        "it, not at what would make a word.\n"
        # This used to say "write an ellipsis as three periods ...", which was
        # written for Japanese and is an instruction to CHANGE the page. lee's
        # chapter 1 prints "거, 취향 참…." and "흐음…." - an ellipsis glyph and
        # then a full stop, which is ordinary Korean typesetting - and the read
        # came back "참...", losing the stop and spelling the ellipsis a way the
        # page does not. Measured over the chapter: 8 lines rewritten to ASCII
        # dots, and 6 of the 8 printed "…." dropped their stop. Three periods
        # belong in the ENGLISH, where a comic font has to draw them; that rule
        # is in the translation prompt and stays there. The transcription is
        # meant to be what is on the paper.
        "- Copy the punctuation EXACTLY as printed, character for character: "
        "an ellipsis is … where the page prints … and ... where it prints ..., "
        "a full stop after an ellipsis (….) is part of the line, and a "
        "long-vowel mark is ー. Do not tidy, normalise, or add stray symbols.\n"
        # THE MARKS THAT ARE PART OF THE LINE. lee, with a crop of 「これから
        # 本番♥」: *"i want teh read text to be able to read stuff like haearts
        # and other thiungs that text can usualy have"*.
        #
        # Nothing above told the reader what to do with one. The rule before
        # this said "punctuation", which a heart is not, and the one after it
        # says never to invent - so the safe reading of the prompt was to drop
        # it, and a mark the artist typeset INSIDE the balloon is part of what
        # the line says. It is the difference between "this is it" and "this
        # is it ♥".
        "- MARKS SET IN THE LINE ARE PART OF THE LINE. A heart, a star, a "
        "music note, a sparkle, a sweat drop, an anger mark - anything typeset "
        "among the words rather than drawn on the artwork - is transcribed "
        "where it stands, as the character it is: ♥ ♡ ★ ☆ ♪ ♫ ※ ⁉ ‼ 💢 💦 ✨. "
        "「これから本番♥」 is `これから本番♥` and never `これから本番`. This is "
        "the same rule as the punctuation one and not licence to invent: a "
        "mark you cannot clearly see is not there.\n"
        # ...and the shape of the line, which the crops were flattening: page
        # 013's narration is printed as three lines and arrived as one.
        "- Keep the LINE BREAKS as printed. A run of writing set as three lines "
        "comes back as three lines separated by \\n, broken in the same places. "
        "Do not re-wrap it, and do not join it into one line.\n"
        # ONE RUN OF WRITING, ONE REGION. lee: *"can you come up with a
        # system or a prompt so that it dont double read"*.
        #
        # The old rule said "two regions almost never hold the SAME text",
        # which only caught the identical case. Page 017's pair is the real
        # shape: the detector put two boxes over ONE vertical column of
        # dialogue, and the reader gave the whole line to one and its tail to
        # the other - そんなので足りるかと and 足りるかよ. Not identical, and
        # the same words read twice.
        #
        # So the rule names the decision instead of the symptom: it belongs to
        # ONE of them, the one whose outline fits it, and the other gets the
        # empty string. The empty one is then removed by `empty_boxes` after
        # the read, which is how the duplicate box disappears without anything
        # having to guess about boxes.
        "- ONE RUN OF WRITING BELONGS TO ONE REGION. If the words inside a red "
        "outline are also inside another region's outline, they are that "
        "column of text answered twice: decide which region they belong to — "
        "the one whose outline fits them most closely — give it the whole "
        "line, and return the EMPTY STRING for the other. Never split one run "
        "of writing between two regions, and never give the same line, or any "
        "PART of the same line, to two regions. An empty answer for a box that "
        "holds nothing of its own is the correct answer, not a failure.\n"
        # The 011 failure. "하이엘프 티리스" came back "하이엘프 타라스": a name
        # the model had never seen, normalised into one that sounds more like a
        # name. The glyphs were 57px and perfectly legible; nothing in this
        # prompt told it not to. lee: *"especialy page 11"*.
        "- A NAME YOU DO NOT RECOGNISE IS STILL THE NAME THAT IS PRINTED. Copy "
        "the syllables you can see. Never replace an unfamiliar name with a "
        "more familiar-sounding one, and never regularise its spelling toward "
        "a name you know. Most names in a comic are invented; being unable to "
        "place one is normal and is not a reason to change it.\n"
        # ...and the dashes the same page lost, which were sitting ON the
        # outline because the box was drawn a few pixels too tight.
        "- Dashes, brackets and quotation marks printed as part of a line are "
        "part of that line: \u201c- 하이엘프 -\u201d keeps both dashes. Include "
        "them even where the outline passes over or beside them.\n\n"
        "You may be given names and terms that have already appeared in this "
        "series. Use them ONLY to settle a glyph you are unsure of — if the "
        "shapes fit a known name, prefer the known spelling. Never insert a "
        "known name into a region that does not visibly contain it.\n\n"
        'Return ONLY JSON, no prose or code fences: '
        '{"regions":[{"id":<int>,"text":"<exact text>"}]} with one entry per '
        "numbered region.")


# ------------------------------------------------------- what kind of box ----
#
# lee: *"i want [it] to try to accura;y lables all the boxes with the sub
# types ... it shoud not creade or dleet boxes just labbles them"*. First asked
# of the proofreader; then, a minute later, *"alos coun;t read text do the same
# thing after its done reading teh text?"* - and he was right, for three
# reasons that all point the same way.
#
# **The read step already pays for a picture.** The proofreader is handed
# `Page(image=np.zeros(...))`; it has never seen the artwork and adding it
# there means buying a page image on every proofread, and a proofread is
# re-run. The reader is looking at the page already.
#
# **These types are decided by DRAWING, not by wording.** A thought balloon is
# a thought balloon whatever it says: cloud outline, no tail. Burst is spiky,
# whisper is broken, a caption box is ruled, big-versus-small is size. The
# proofreader knows the English and the reader is looking at the ink, and it is
# the ink that settles every one of these.
#
# **The proofreader cannot see half the boxes.** `build_proofread_payload`
# drops `kind == "sfx"` on purpose, so it could never have told Big / impact
# from Small / background at all.
#
# THE PICTURE IS NOT THE READER'S PICTURE. The reader's default is one crop per
# box, padded 25% around the WRITING - and a balloon is drawn well outside its
# writing. Measured on lee's chapter 3, 141 balloons with a traced outline:
#
#     the crop holds the whole outline      21 of 141   (15%)
#     median share of the outline in it     0.66
#     under 90% of the outline             108 of 141
#
# So a labeller riding on the crops would be judging balloon shape from two
# thirds of a balloon. It gets its own picture: the whole page at 768px, which
# is ~553 image tokens - a third of the 1,747 a full-resolution page costs, and
# enough to read every number tag and see every outline. One request a page.
LABEL_SIDE = 768

# How each type is DRAWN.
#
# Written against reference charts lee sent - *"use these to helpyou understand
# teh buble types"* - and against his own pages, where the two disagree. Four
# charts, plus AnimeOutline's tutorial and Blambot's grammar page. What they
# agree on is in here; where they DISAGREE is in `LABEL_APART` below, because a
# disagreement between traditions is exactly where a labeller goes wrong.
#
# Keyed by the shipped sub-type keys, because those are the only ones a model is
# ever offered - see `kinds.labelling_vocabulary`.
LABEL_LOOKS = {
    "bubble": "a plain balloon, smooth closed outline, usually with a tail "
              "pointing at whoever is speaking. THE DEFAULT - a balloon that "
              "is not clearly one of the others is this one, and so is one "
              "whose shape says something we have no name for",
    # Three drawings, not one. lee's first chart files vertical narrow strips,
    # plain rectangles AND rounded "THREE DAYS AGO" pills all under captions;
    # an earlier version of this line said "square-cornered" and would have
    # missed two of the three.
    "narration": "a BOX rather than a balloon, and no tail. Any of: a plain "
                 "rectangle, a rounded-corner rectangle or pill (often a date "
                 "or a time - \"three days ago\"), or a long narrow strip laid "
                 "down the side of the page. Holds narration or a caption, not "
                 "somebody speaking",
    # Written against real pages as well as the charts. lee's page 017 has two
    # thought balloons and neither is the textbook one: soft LUMPY ovals with
    # no trail of circles at all. An earlier draft said "scalloped, AND a trail
    # of small circles", which would have called both of them plain speech - a
    # description narrow enough to match only the diagram is a description that
    # only labels diagrams.
    #
    # The FLASH balloon used to be the last clause of this one, on lee's own
    # instruction - *"flash bubbles shub be considered thoughts bubbles"* - and
    # he took it back after seeing one holding a line a character says out loud
    # to somebody standing in front of her: *"this is calsiified as a thught
    # bubble, its not"*. It has a type of its own now - `fancy`, below.
    #
    # Filing it here did not merely mislabel it, it aimed the TYPESETTING at
    # the wrong thing: a thought balloon is set in italic to say "not said
    # aloud", and this is said aloud.
    "thought": "not a smooth oval, and no tail pointing at a mouth, AND "
               "nothing drawn in the space around it. Any of: a cloud or "
               "scalloped outline; a soft lumpy irregular one; or a trail of "
               "small separate circles where a tail would be. An only "
               "slightly irregular outline with no tail is this one too. "
               "UNVOICED - what the character is thinking, not saying",
    # THE TELL IS WHAT IS DRAWN AROUND IT, NOT THE OUTLINE.
    #
    # The first version of this was about the FLASH shape alone - a smooth
    # core with a halo of fine radial spikes - because that was the balloon
    # lee sent. His second example is nothing like it: a soft LUMPY outline
    # with little flowers dotted in the space around it, holding "R-Really?!".
    # lee: *"here is another exmale of a happy bubble"*.
    #
    # By outline alone that one is a textbook thought balloon, and it is a
    # character speaking. What the two examples have in common is not their
    # edge, it is the DECORATION outside it - sparkles, small stars, flowers,
    # a halo of spikes - which is the artist saying *delighted*, and delight
    # is a thing you say out loud.
    #
    # So the rule is about the space around the balloon, and `thought` has
    # gained the matching clause: a lumpy outline with nothing round it.
    "fancy": "MARKS DRAWN IN THE SPACE AROUND THE BALLOON - sparkles, small "
             "stars, flowers, hearts, or a halo of many fine radial spikes "
             "like a starburst or a glow. The outline itself may be anything: "
             "a smooth oval, or lumpy and cloud-like. It is the decoration "
             "outside it that decides, and it means the line is SPOKEN with "
             "delight, excitement or flattery - not thought",
    # Page 017's 倍…!? is a FACETED balloon - straight segments meeting at
    # corners - and nothing about it is star-shaped, so "star-shaped" alone
    # would have missed it.
    "shout": "the outline itself is a ZIGZAG: spiky, jagged, star-shaped, "
             "exploding, or drawn from straight segments meeting at angles "
             "rather than as a curve. The points are part of the wall of the "
             "balloon - few and large enough to count as its shape - and it "
             "counts filled solid black as well as white. Usually shouting or "
             "a shock, and the type inside is often larger or heavier",
    "whisper": "the outline is BROKEN - drawn as a dashed or dotted line "
               "instead of a continuous one - and the type inside is often "
               "small. A balloon deliberately drawn faint",
    "freefloat": "writing lying straight on the artwork with nothing drawn "
                 "round it. THE DEFAULT for unboxed writing",
    "narration_free": "narration or a caption lying on the artwork with no "
                      "shape round it - a voice telling the story rather than "
                      "a character speaking",
    "aside": "a small muttered remark set beside a character, often in smaller "
             "or scratchier type than the dialogue - an aside, not a line",
    "sign": "writing that is PART OF THE SCENE and not part of the "
            "conversation: a shop sign, a banner, a label on a box, the cover "
            "of a book, a sign on a wall",
    "sfx": "a drawn sound. THE DEFAULT for one",
    "sfx_big": "a drawn sound that is LARGE - it dominates its panel, or runs "
               "across a good part of the page",
    "sfx_small": "a drawn sound that is SMALL - a little noise tucked beside a "
                 "character or an object, not an impact",
}

# The pairs that actually get confused, and the shapes that look like one of
# ours and are not.
#
# Every line here is a case where two of the descriptions above could both be
# read as fitting, or where a real balloon convention has no type in this app
# and would otherwise be swept into the nearest one. A list of definitions
# answers the easy boxes; this is for the ones that decide how good the whole
# pass is.
#
# The last four are the important ones. Manga draws several balloons this app
# has no name for - weak or fading speech, gloom, an electronic voice, a stiff
# formal one - and each of them has a shape that one of our descriptions would
# happily claim. A wavy balloon is not a cloud. An angular radio balloon is not
# a burst. Getting a box wrong is worse than leaving it plain, so each of them
# is sent to its family's default BY NAME rather than left to the general
# when-in-doubt rule, which only fires when the model is already unsure.
LABEL_APART = (
    # The collision lee's ruling creates, and the one most worth spelling out:
    # a flash balloon IS spiky, and the burst description is about spikes.
    "A FLASH balloon and a BURST are both spiky and are not the same thing. A "
    "flash has a smooth oval core with a halo of MANY FINE hair-like spikes "
    "around it, like a glow or a starburst - answer fancy. A burst has FEW "
    "LARGE points that are the wall of the balloon itself, a zigzag you could "
    "trace - answer shout.",
    "A FANCY balloon and a THOUGHT are told apart by what is drawn AROUND "
    "the balloon, not by its outline. Sparkles, small stars, flowers, hearts "
    "or a halo of fine spikes in the space outside it - answer fancy, even "
    "when the outline is lumpy or cloud-like, because that decoration is the "
    "artist drawing delight and delight is spoken aloud. A cloud, scalloped "
    "or lumpy outline with NOTHING drawn round it - answer thought.",
    "A tail is what separates speech from thought, but a MISSING tail is not "
    "enough on its own: a smooth oval with no tail - or with a small notch or "
    "inward-pointing tail - is usually a character speaking from off-panel, "
    "and that is plain speech. Read it as thought only when the outline is "
    "also cloud-like or lumpy.",
    "A rectangle with a TAIL is somebody speaking in a square balloon, which "
    "is plain speech. A caption box has no tail.",
    "A big sound effect against a small one is judged against the PAGE and its "
    "panels, not against the other effects on it: a page whose sounds are all "
    "small does not contain a big one.",
    "A sign is part of the scene - it would still be there if nobody were "
    "speaking. Narration on the art is a voice, and belongs to no object in "
    "the picture.",
    "A BLACK FILL is not a type. A balloon filled solid black is drawn that "
    "way for menace or dread, and it can be any shape: judge it by its "
    "OUTLINE exactly as if it were white.",
    "A WAVY or wobbly outline - continuous, but rippling - is weak, fading or "
    "uneasy speech. It is not a cloud and not a broken line: answer plain "
    "speech.",
    "A balloon with corners AND a jagged lightning-bolt tail is a voice from a "
    "radio, a phone or a speaker. Answer plain speech, not a burst.",
    "A balloon whose bottom edge MELTS or drips is sadness. Answer plain "
    "speech.",
)


# The ONE exception to "the family cannot change", and it is switched off
# unless the project asked for it.
#
# lee's own switch says why: *"Find text tells these two apart by shape, and
# they have the same shape - loose text on the art, no balloon. Reading the
# words settles it."* Everything else in this prompt is decided by how a box is
# DRAWN, and for this one pair that rule is exactly wrong - there is nothing to
# look at, which is the whole reason the detector cannot do it either.
#
# It ran at translation time until lee asked: *"can read text do this before
# chnage teh sub type and after reading?"* - and it belongs here, because the
# reading is what settles it and the reading has already happened. Doing it
# first also means the sub-type is chosen INSIDE the corrected family instead
# of being assigned to the wrong one and stranded there.
SWAP_RULE = (
    "ONE EXCEPTION, and only between Sound effect and Freefloat text. Those "
    "two are both loose writing on the artwork with nothing drawn round them - "
    "they have the SAME SHAPE, so for this pair alone the shape decides "
    "nothing and the WORDS decide. Each of those regions is listed with what "
    "was read in it.\n"
    "A noise is a sound effect: ドン, ザッ, a drawn crash, a thump, a rustle - "
    "written to be HEARD rather than said.\n"
    "A phrase somebody is saying or thinking is Freefloat text, however small "
    "and however unboxed: a muttered aside, a label, a line of narration.\n"
    "Answer with a type from the OTHER of those two families when the words "
    "plainly say so, and leave it alone otherwise. This does not apply to "
    "balloons: a bubble stays a bubble.\n\n")


ANGLE_RULE = (
    "AND THE ANGLE OF THE WRITING, for the regions marked `angle?` in the "
    "listing and no others. Those are the ones with no balloon drawn round "
    "them - loose writing set straight onto the artwork - and that writing is "
    "very often tilted, which the typesetting has to match or the English "
    "sits level on a page where nothing else is.\n"
    "- Give it in DEGREES, as a number, positive ANTICLOCKWISE, 0 for level.\n"
    "- It is the lean of the BASELINE the characters sit on, not the shape of "
    "the box round them and not the direction of the tail of anything.\n"
    "- Writing set in a vertical column is NOT tilted: a column running "
    "straight down the page is 0, not 90. Answer the lean of the column "
    "itself.\n"
    "- The honest answer is usually 0. Give a number other than 0 only when "
    "the tilt is plain to see, and keep it between -60 and 60. A wrong angle "
    "is worse than a level line, because a level line is what the page would "
    "have had anyway.\n"
    "- Omit `angle` entirely for any region not marked `angle?`.\n\n")


def build_label_system(vocab: dict, source: str = "Japanese",
                       may_swap: bool = False,
                       want_angle: bool = False) -> str:
    """The labeller's instructions, built from the types it may actually use.

    The vocabulary is grouped BY FAMILY and the prompt is written family by
    family, because the family is the one thing this step may not change. lee
    chose that: the family decides how a box is cleaned and typeset, and it was
    settled at detection from geometry - whether there is a balloon drawn round
    the writing - which a detector reading pixels does better than a model
    reading a thumbnail. A wrong sub-type costs a typeface. A box moved from
    balloon to sound effect stops being cleaned as a balloon and drops out of
    proofreading entirely.
    """
    lines = []
    for fam, items in vocab.items():
        if not items:
            continue
        lines.append("%s (%s):" % (_kinds.FAMILY_LABELS.get(fam, fam), fam))
        for key, label in items:
            look = LABEL_LOOKS.get(key, "")
            lines.append('  "%s" — %s%s' % (key, label,
                                            (": " + look) if look else ""))
    return (
        f"You are looking at one page of a {source} comic. Every box that has "
        "been found on it is outlined in RED and carries a red number tag.\n\n"
        "Your job is to say what KIND of box each one is. You are not "
        "transcribing, translating or correcting anything, and you are not "
        "deciding which boxes should exist — the boxes are already decided.\n\n"
        "Each region is listed with the family it belongs to. THE FAMILY "
        "CANNOT CHANGE. Choose only from the types listed under that region's "
        "own family; a type from another family is not an available answer, "
        "however well it fits.\n\n"
        + (SWAP_RULE.format(source=source) if may_swap else "")
        + "The types:\n" + "\n".join(lines) + "\n\n"
        "Telling them apart:\n"
        + "\n".join("- " + s for s in LABEL_APART) + "\n\n"
        "How to decide:\n"
        "- Go by HOW THE BOX IS DRAWN, not by what it says. A thought balloon "
        "holding an ordinary sentence is still a thought balloon, and an "
        "excited line in a plain smooth balloon is still plain speech.\n"
        "- WHEN IN DOUBT, SAY SO: set \"sure\" to false and the box keeps "
        "whatever type it already has. Every one of these boxes is already "
        "labelled and usable; you are only being asked to improve on one "
        "where the drawing PLAINLY says something more specific. A confident "
        "wrong label is worse than leaving a box alone, because somebody has "
        "to find it and undo it.\n"
        "- \"sure\" is not a formality. Answer false whenever the shape is "
        "small, cut off by the panel edge, partly hidden behind a character, "
        "or simply ambiguous - and false is a complete answer on its own.\n"
        "- Anything outlined in GREY is not yours to label.\n\n"
        + (ANGLE_RULE if want_angle else "")
        + "Return one entry for every numbered region, and no others. Return "
        'ONLY JSON, no prose or code fences: '
        '{"regions":[{"id":<int>,"kind":"<one of the keys above>",'
        '"sure":true|false%s}]}'
        % (',"angle":<number>' if want_angle else ""))


# Which families are worth an angle. lee named two - *"onlu for freefloat and
# sfx"* - and then, having seen outside text set on a slant: *"also make all
# teh freefloast text be start no more angle"*.
#
# So it is the sound effects, and the reading fills in the ones the ink
# measurement at Find text never reached. Asking about outside text as well
# would be buying an answer nothing acts on: `typeset.fit_region` sets a
# freefloat block level on purpose now, and it says so there.
ANGLE_KINDS = ("sfx",)
ANGLE_LIMIT = 60.0


def label_kinds(page: "Page", ctx: "SeriesContext", png: bytes, vocab: dict,
                client=None, model: str = "", max_retries: int = 1,
                angles: "Optional[dict]" = None) -> dict:
    """Ask what kind of box each region is. Returns {region_id: kind}.

    Only answers that survive every rule are returned, so the caller can apply
    the lot without re-checking: a key that is not in the vocabulary is
    dropped, and so is one whose family differs from the box's own. The prompt
    says both; this is the half that does not depend on a model complying.

    An id that is not on the page is dropped too - which is the whole of "it
    shoud not creade or dleet boxes". This function returns labels for boxes
    that already exist and has no way to say anything else.

    Pass a dict as `angles` to also ask HOW THE WRITING LEANS, and it is
    filled with {region_id: degrees}. lee: *"is posible while looking at the
    box type with reas text ask it to give the angle of the text for the
    typesetter"* - *"onlu for freefloat and sfx"*.

    Those two families and no others, and that is not an arbitrary pair: they
    are the writing with nothing drawn round it, which is the writing that
    leans. A balloon's words follow the balloon. Asking here rather than in a
    pass of its own is free of a request: this step is already looking at a
    picture of the whole page with every box outlined on it, which is exactly
    what an angle has to be read from.
    """
    regions = [r for r in page.regions if not getattr(r, "own_text", False)]
    if not regions or not png or not vocab:
        return {}
    kind_ok = {key: fam for fam, items in vocab.items() for key, _l in items}
    if not kind_ok:
        return {}

    if client is None:
        client, model, backend = make_client(
            backend=ctx.backend, base_url=ctx.base_url,
            model=ctx.model or MODEL, api_key=ctx.api_key,
            safety=getattr(ctx, "safety", "") or "",
            step_name=getattr(ctx, "step_name", "") or "")
    else:
        backend = "openai" if isinstance(client, OpenAICompatClient) \
            else "anthropic"

    fam_of = {r.id: _kinds.family_of(getattr(r, "kind", "") or "")
              for r in regions}
    order = sorted(regions, key=lambda r: (getattr(r, "order", 0), r.id))
    # Sound effect against outside text is settled by the WORDS, not the shape -
    # see `SWAP_RULE` - so those regions are listed WITH what was read in them
    # and nothing else is. A page of transcriptions would be a second copy of
    # the reading in a prompt that is about the drawing.
    may_swap = bool(getattr(ctx, "retype_kinds", False))

    # WHICH boxes an angle is wanted for, decided here and marked in the
    # listing rather than described in the prompt. The prompt cannot see the
    # page's families; the listing is the only place the two agree.
    ask_angle = {r.id for r in order
                 if angles is not None and fam_of[r.id] in ANGLE_KINDS}

    def _row(r):
        row = "%d: family %s, currently %s" % (r.id, fam_of[r.id],
                                               getattr(r, "kind", "") or "?")
        if may_swap and fam_of[r.id] in RETYPE_KINDS:
            said = " ".join((getattr(r, "src_text", "") or "").split())[:60]
            if said:
                row += ", reads %s" % said
        if r.id in ask_angle:
            row += ", angle?"
        return row

    listing = "\n".join(_row(r) for r in order)
    system = build_label_system(vocab, source_language(ctx.medium, ctx.source),
                                may_swap=may_swap,
                                want_angle=bool(ask_angle))
    import base64
    b64 = base64.b64encode(bytes(png)).decode("ascii")

    want = {r.id for r in order}
    last_err = ""
    for _attempt in range(max_retries + 1):
        _stopping.check()
        user = ("The regions on this page, in reading order:\n" + listing
                # A box somebody typed themselves is drawn and numbered on the
                # picture like any other, and it is NOT in the listing - there
                # is no writing in the artwork under it, so there is no drawing
                # to read a kind off. Without this line the prompt's "one entry
                # per numbered region" and the listing disagree, and the model
                # is left to decide which of the two to obey.
                + "\n\nSome boxes on the picture may not be in that list. "
                  "Ignore those; answer for the listed regions only.\n\n"
                  "Give the kind of each. Answer with the family's default "
                  "wherever the drawing does not plainly say otherwise.")
        if last_err:
            user += "\n\nYour previous reply was rejected: %s. Fix it." % last_err
        try:
            text = _ask_vision(client, backend, model or MODEL, system, user,
                               b64)
            data = _extract_json(text)
        except Exception as e:
            last_err = str(e)[:200]
            continue
        items = [it for it in (data.get("regions") or []) if isinstance(it, dict)]
        if not items:
            last_err = "regions was empty"
            continue
        out: dict[int, str] = {}
        for it in items:
            try:
                rid = int(it.get("id"))
            except (TypeError, ValueError):
                continue
            if rid not in want:
                continue                  # not a box on this page
            # THE ANGLE IS READ FIRST AND KEPT SEPARATELY, so a region whose
            # kind is rejected below still gives up its angle. The two answers
            # are about different things - what the box IS, and which way its
            # writing leans - and one of them being unusable says nothing
            # about the other.
            if rid in ask_angle and "angle" in it:
                try:
                    deg = float(it.get("angle"))
                except (TypeError, ValueError):
                    deg = None
                # A number outside the range asked for is not clamped into it.
                # Clamping turns "I have misread this box as sideways" into a
                # confident 60-degree lean, which is the wrong answer stated
                # firmly; dropping it leaves the box level, which is what the
                # page would have had anyway.
                if deg is not None and deg == deg and abs(deg) <= ANGLE_LIMIT:
                    angles[rid] = round(deg, 1)
            # AN UNSURE ANSWER IS NOT AN ANSWER. lee: *"if the ai is not
            # confident of a box acthergory it shoud not change the type"*.
            #
            # The rule it replaces was "when in doubt, answer the family's
            # default", which is not leaving a box alone - it is CHANGING it,
            # to plain speech, on no evidence. A box that somebody labelled by
            # hand, or that the detector got right, was overwritten by a shrug.
            #
            # Enforced here as well as asked for in the prompt, for the same
            # reason the family rule is a few lines down: a prompt is a
            # request.
            #
            # MISSING reads as sure, and that is the safe direction rather
            # than the strict one. A model that ignores the field would
            # otherwise have every one of its answers dropped and this step
            # would quietly stop doing anything at all - a silent total
            # regression, which is worse than the thing being fixed. Only an
            # explicit `false` throws an answer away.
            if it.get("sure") is False:
                continue
            got = str(it.get("kind") or "").strip()
            if got not in kind_ok:
                continue                  # not a type it was offered
            if kind_ok[got] != fam_of[rid] and not (
                    # THE ONE EXCEPTION, and it is off unless the project asked
                    # for it. Sound effect and outside text have the same shape,
                    # so the words decide - see `SWAP_RULE`. Enforced here as
                    # well as asked for in the prompt, for the same reason the
                    # family rule is: a prompt is a request.
                    may_swap and kind_ok[got] in RETYPE_KINDS
                    and fam_of[rid] in RETYPE_KINDS):
                continue                  # the family is not its to change
            out[rid] = got
        return out
    return {}


# ---------------------------------------------------------------- names ----
# Two different failures, both of which poison the running character sheet and
# then every later chapter that starts from it:
#
#   1. The model invents a proper name for someone the page never names. Two
#      palace attendants become "Glow" and "Rofan" eleven pages before those
#      characters actually appear.
#   2. The same person is written two ways - "Glow" one page, "Glou" the next -
#      and setdefault() happily keeps both, so the sheet now disagrees with
#      itself about who exists.
#
# The cure for (1) is evidence: a name may only join the sheet if it is
# actually written somewhere. The cure for (2) is a canonical form that ignores
# the ways a Japanese name can be romanized.

# Titles are not names. "Lady Ada" is evidence for Ada, not for "Lady".
_TITLE_WORDS = {
    "lady", "lord", "sir", "madam", "master", "mistress", "miss", "mr", "mrs",
    "ms", "prince", "princess", "king", "queen", "duke", "duchess", "count",
    "countess", "baron", "baroness", "captain", "general", "doctor", "dr",
    "saint", "st", "the", "of", "young", "elder", "old", "big", "little",
}
# Japanese honorifics ride along on a name and are not part of it.
_HONORIFICS = ("sama", "san", "chan", "kun", "dono", "senpai", "sensei",
               "tan", "shi", "senpai")


def canon_name(s: str) -> str:
    """A name reduced to what survives romanization, so two spellings of one
    person collide.

    Japanese has no l/r distinction and no v, long vowels are written half a
    dozen ways (ou / oh / oo / o / ow), and doubled consonants come and go. Fold
    all of that away and Glow, Glou, Grow and Grou become the same string -
    which is the point: they are the same man.
    """
    import re as _re
    t = _re.sub(r"[^a-z]", "", str(s or "").lower())
    for h in _HONORIFICS:                       # "adasama" -> "ada"
        if len(t) > len(h) + 1 and t.endswith(h):
            t = t[: -len(h)]
            break
    t = t.replace("l", "r").replace("v", "b")
    t = _re.sub(r"(ou|oh|oo|ow)", "o", t)
    t = _re.sub(r"(uu|uh)", "u", t)
    t = _re.sub(r"(ei|ee)", "e", t)
    t = _re.sub(r"(.)\1+", r"\1", t)            # kitto / kito, -nn- / -n-
    return t


def name_tokens(name: str) -> list[str]:
    """The parts of a name that actually identify somebody - titles dropped."""
    import re as _re
    words = [w for w in _re.split(r"[^A-Za-z]+", str(name or "")) if w]
    keep = [w for w in words if w.lower() not in _TITLE_WORDS]
    return keep or words


def same_person(a: str, b: str) -> bool:
    """True when two written names are one person.

    Canonical equality first - that is the principled half, and it is what
    catches Glow/Glou. Then a one-character slip on a name long enough for the
    slip to be a typo rather than a different name: Leonora/Leonore yes,
    Mimi/Momi no, because at four letters a single letter IS the difference
    between two people.
    """
    ca, cb = canon_name(a), canon_name(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    if min(len(ca), len(cb)) < 5 or abs(len(ca) - len(cb)) > 1:
        return False
    import difflib
    m = difflib.SequenceMatcher(None, ca, cb)
    # one edit's worth of difference on a name of five letters or more
    return (max(len(ca), len(cb)) - int(round(m.ratio() * (len(ca) + len(cb)) / 2))) <= 1


def match_known(name: str, known) -> str | None:
    """The spelling already on the sheet for this person, if they are on it."""
    for k in known:
        if same_person(name, k):
            return k
    return None


def name_evidence(ctx: "SeriesContext", texts=()) -> set:
    """Every name the story has actually written down, in canonical form.

    Drawn from what the editor wrote (the synopsis and the sheet), what the
    series has established (the glossary), and what is said out loud on the
    pages in hand. A character gets named when somebody addresses them - "Ada,
    what's wrong?" - so the dialogue is the strongest evidence there is.
    """
    import re as _re
    pool: list[str] = []
    pool += [str(k) for k in (getattr(ctx, "characters", None) or {})]
    pool.append(str(getattr(ctx, "synopsis", "") or ""))
    gl = getattr(ctx, "glossary", None) or {}
    pool += [str(k) for k in gl] + [str(v) for v in gl.values()]
    pool += [str(t) for t in (getattr(ctx, "previous_page_tail", None) or [])]
    pool += [str(t) for t in (texts or [])]
    out = set()
    for chunk in pool:
        for w in _re.split(r"[^A-Za-z]+", chunk):
            c = canon_name(w)
            if len(c) >= 2:
                out.add(c)
    return out


def unevidenced(name: str, evidence: set) -> bool:
    """True when nothing anywhere writes this name - so the model made it up.

    A name is cleared by ANY of its identifying parts appearing: "Rofan the
    Mercenary" passes as soon as Rofan is written somewhere. Only a name with
    no support at all is rejected.
    """
    toks = [canon_name(t) for t in name_tokens(name)]
    toks = [t for t in toks if len(t) >= 2]
    if not toks:
        return False              # nothing name-like in it; not our problem
    return not any(t in evidence for t in toks)


# Role words that mark a one-off / unnamed speaker. The character sheet is for
# NAMED, recurring cast; a bit part like "Guard A" or "Petitioner's Father"
# still gets a per-line speaker but must not clutter the running sheet.
GENERIC_ROLE_WORDS = {
    "guard", "guards", "bystander", "bystanders", "crowd", "onlooker",
    "onlookers", "passerby", "narrator", "narration", "petitioner", "soldier",
    "villager", "mob", "spectator", "commoner", "citizen", "patient", "kid",
    "child", "children", "boy", "girl", "townsperson", "attendant", "servant",
    "maid", "shopkeeper", "merchant", "priest", "nun", "audience", "student",
    "voice", "someone", "somebody", "people", "figure", "stranger",
}


def is_generic_speaker(name: str) -> bool:
    """True for an unnamed bit part ("Guard A", "Petitioner's Father", "Crowd"),
    so it is kept off the running character sheet. A real proper name has no
    generic role word in it and passes through."""
    import re as _re
    words = [w for w in _re.sub(r"[^a-z ]", " ", (name or "").lower()).split()
             if w]
    if not words:
        return True
    return any(w in GENERIC_ROLE_WORDS for w in words)


# ------------------------------------------------------------- the glossary
#
# A glossary entry is stored as {source term: canon rendering}, and the
# rendering carries its own short note in brackets - "Tarel (the copper coin)".
# The panel shows it as name | note, the same shape as a character row, and the
# note travels to the translator with the name.
#
# These three are `glossName` / `glossNote` / `glossValue` from
# `static/js/project.js`, written out again in Python because the enforcement
# below has to agree with the panel about where a name ends and its
# description begins. A test holds the two in step. Note what the dash rule
# needs: SPACES around the dash, so "Half-Moon Gate" is a name with no note in
# it and not a gate called "Half" described as "Moon Gate".

_GLOSS_SPLIT = re.compile(r"\s*[（(]|\s+[—–-]\s+")
_GLOSS_BRACKET = re.compile(r"[（(]([^)）]*)[)）]")
_GLOSS_DASH = re.compile(r"\s+[—–-]\s+(.+)$")


def gloss_name(v) -> str:
    """`"Lulu (white rabbit)"` -> `"Lulu"`."""
    return _GLOSS_SPLIT.split(str(v or ""), 1)[0].strip()


def gloss_note(v) -> str:
    """...and the other half: `"Lulu (white rabbit)"` -> `"white rabbit"`."""
    t = str(v or "")
    m = _GLOSS_BRACKET.search(t)
    if m:
        return m.group(1).strip()
    d = _GLOSS_DASH.search(t)
    return d.group(1).strip() if d else ""


def gloss_value(name, note) -> str:
    """Put the two halves back together the one way they are stored."""
    name, note = str(name or "").strip(), str(note or "").strip()
    return f"{name} ({note})" if note else name


# ---------------------------------------------------------- one sentence?
#
# Two blocks of writing inside one balloon are either one sentence the typesetter
# broke in two, or two things said. They look identical to a detector, and the
# detector used to guess: `detect_comictext` linked every box a single block
# split into. That guess was wrong on lee's hot-spring balloon, and a link is
# not a small wrong thing - the reader is told neither half may complete the
# sentence, the translator is told to split one English sentence between them,
# and the typesetter re-cuts the balloon by English length.
#
# The pixels cannot answer it. The WORDS can, and by the time Read text has
# finished they exist. So the question is asked here instead, once, and asked
# narrowly.

# What an author writes at the break when a line runs on. The same set
# `strip_added_dashes` knows about, for the same reason: these are the marks
# that mean "this is not the end".
_RUNS_ON_END = "—–―─━〜～…‥"
_RUNS_ON_START = "—–―─━〜～…‥"

# ...and what ends a sentence, which settles it the other way whatever else is
# on the line.
_ENDS_IT = "。．！？!?"


def reads_on(first: str, second: str) -> bool:
    """Does `first` run on into `second`?

    Deliberately narrow. Manga drops the full stop constantly, so "no ending
    punctuation" would link half the balloons in a chapter, and a link invented
    where there is none is worse than a link missed: it makes the translator
    write one sentence across two speeches. So the only thing taken as evidence
    is the author's own typography at the break - a dash or an ellipsis trailing
    the first block, or leading the second. That is what a typesetter writes when
    a line is carried, and it is the whole signal.

    A missed one costs a press of L. An invented one costs a page.
    """
    a = (first or "").strip()
    b = (second or "").strip()
    if not a or not b:
        return False
    # Closing brackets and quotes sit outside the mark, so they come off first.
    a = a.rstrip("」』）)】〕》”\"'")
    b = b.lstrip("「『（(【〔《“\"'")
    if not a or not b:
        return False
    if a[-1] in _ENDS_IT:
        return False
    return a[-1] in _RUNS_ON_END or b[0] in _RUNS_ON_START


def link_sections(regions) -> int:
    """Link the sections of each balloon that read on, and unlink those that do
    not. Returns how many groups were linked.

    Asked of the whole page after a read, so a re-read can change its mind: a
    box whose text was corrected from a fragment to a whole sentence should
    stop being half of one.

    Only ever touches boxes that share a `box_group` - sections of one balloon,
    which is the only case the detector was guessing about. A link somebody set
    by hand between two separate balloons is not in a group and is not touched.
    """
    groups: dict = {}
    for r in regions:
        g = int(getattr(r, "box_group", 0) or 0)
        if g:
            groups.setdefault(g, []).append(r)

    used = max([int(getattr(r, "link", 0) or 0) for r in regions] or [0])
    done = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda r: (r.order if r.order >= 0 else 0, r.id))
        joined = all(reads_on(members[k].src_text, members[k + 1].src_text)
                     for k in range(len(members) - 1))
        if joined:
            used += 1
            done += 1
        for r in members:
            r.link = used if joined else 0
            r.link_kind = "sentence" if joined else ""
    return done


def is_a_person(rendering: str, characters) -> str:
    """Which character this glossary rendering is, if it is one at all.

    The prompt is already clear that **a person NEVER goes in
    glossary_additions** - a named character belongs on the character sheet
    and nowhere else, so that no one is listed twice. Nothing enforced it, and
    lee's chapter came back with

        이델 캐니언 -> "Edel Canyon (the canyon location)"

    which is the heroine's maiden name filed as a place, because 캐니언 reads
    as the English word. The glossary is what every LATER chapter starts from,
    so a wrong entry there outlives the chapter that made it.

    The test is narrow on purpose, and the entry it must NOT catch is the one
    sitting beside it on lee's own sheet: `랭카스터 -> "Lancaster (the ducal
    house and family name)"`, which is a real place-ish term that happens to
    share a word with Edel Lancaster. So:

    * the rendering is exactly TWO name-shaped words - the shape of a personal
      name, and not "Lancaster" (one) or "Edel Canyon Bridge" (three);
    * no possessive and no lower-case word in it, so "Phara's Temple" and
      "Hall of Mirrors" are left alone;
    * and its FIRST word is the first word of a name on the character sheet.
      A surname shared with a house is not enough - "Lancaster" is not Edel's
      given name, so the ducal house passes. A GIVEN name is what a person is
      re-introduced under: a maiden name, a title, a pen name.

    Returns the sheet name it collided with, or "".
    """
    parts = str(rendering or "").split()
    if len(parts) != 2:
        return ""
    if any(len(p) < 3 or not p[0].isupper() or _bare(p) != p
           or not p.isalpha() for p in parts):
        return ""
    for who in (characters or {}):
        first = str(who).split()
        if first and first[0].lower() == parts[0].lower() \
                and str(who).lower() != str(rendering).lower():
            return str(who)
    return ""


def merge_glossary(sheet: dict, adds: dict, characters=None) -> list:
    """Fold proposed terms into the glossary. Returns what was refused.

    **Every term must say what it is.** lee, looking at a panel where nine of
    eleven terms had an empty note: *"make it so that the ai alway writes a
    discption"*. A bare rendering is refused - a glossary that says "Tarel" and
    nothing else tells the next page's translator only that Tarel is spelled
    Tarel, which it could already see.

    Two rules follow from that, and they are opposites on purpose:

    * A described entry **fills in** a bare one already on the sheet. That is
      the way out for a glossary that already has nine empty rows: the prompt
      asks the model to re-propose anything it was given without a bracket, and
      this is what lets the answer land.
    * A described entry **never re-words** an already-described one. First
      sighting is canon, exactly as it is for the character sheet - otherwise
      every page gets a vote on what a term means and the sheet is whatever the
      last page happened to say.

    The rendering itself keeps the sheet's spelling when there is one, for the
    same reason: the sheet is canon and a later page only extends it.

    This lives here, and `ctx.glossary.update()` lives nowhere, so the rule is
    about the SHEET and not about one route into it. It used to be applied by
    the live translator only, which meant a hand-typed reply pasted into the
    upload box could put anything at all on the sheet.
    """
    refused = []
    for k, v in (adds or {}).items():
        term, rendering = str(k).strip(), str(v or "").strip()
        if not term or not rendering:
            continue
        name, note = gloss_name(rendering), gloss_note(rendering)
        if not name:
            continue
        if not note:
            refused.append(f"{name} (no description — say what it is)")
            continue
        who = is_a_person(name, characters)
        if who:
            refused.append(f"{name} (that is {who} — a person belongs on the"
                           " character sheet, not the glossary)")
            continue
        have = sheet.get(term)
        if have is not None:
            if gloss_note(have):
                continue                    # already described; canon stands
            name = gloss_name(have) or name  # fill the note in, keep the name
        sheet[term] = gloss_value(name, note)
    return refused


def merge_characters(sheet: dict, adds: dict, evidence: set, is_generic=None) -> list:
    """Fold proposed characters into the running sheet. Returns what was refused.

    Three ways in: an existing person under the spelling the sheet already uses
    (never a second entry), a new person the text actually names, or nothing.
    """
    is_generic = is_generic or is_generic_speaker
    refused = []
    for k, v in (adds or {}).items():
        name, note = str(k).strip(), str(v).strip()
        if not name:
            continue
        known = match_known(name, sheet)
        if known:
            # Already on the sheet. First sighting stays canon - later pages
            # extend the sheet, they do not re-decide someone's pronouns - but
            # the alternative SPELLING is dropped rather than added beside it.
            if known != name:
                refused.append(f"{name} (already on the sheet as {known})")
            continue
        if is_generic(name):
            refused.append(f"{name} (an unnamed bit part)")
            continue
        if unevidenced(name, evidence):
            refused.append(f"{name} (this name is written nowhere in the story)")
            continue
        sheet[name] = note
    return refused


# ------------------------------------------------- canon spelling enforcement
#
# The proofread prompt says the sheet's spellings are canon, and the model
# mostly obeys. "Mostly" is the problem: one page in a chapter renders Leonora
# as Leonore and nothing downstream notices, because a page is proofread alone
# and every page looks internally consistent. So after the model has had its
# say, the same canonical form that keeps Glow and Glou from becoming two
# people is used to snap spellings back mechanically.
#
# The danger is obvious: canon_name folds l into r and collapses vowels, so
# "Grow" and "Glow" are the same string, and rewriting the verb into the man
# would be worse than the drift it fixes. Three guards stand in the way - a
# word must be capitalized, must not be a common English word, and must not be
# a word the chapter itself uses in lower case somewhere.

# Capitalized at the start of a sentence does not make it a name. Kept small
# and biased toward words that actually collide with name-shaped strings once
# canon_name has folded them.
_COMMON_CAPS = {
    "about", "after", "again", "against", "all", "almost", "alone", "along",
    "already", "also", "although", "always", "and", "another", "answer",
    "any", "anyone", "anything", "are", "around", "away", "back", "because",
    "been", "before", "behind", "being", "better", "between", "both", "bring",
    "but", "call", "came", "can", "cannot", "come", "could", "did",
    "does", "done", "down", "each", "either", "else", "enough", "even",
    "ever", "every", "everyone", "everything", "except", "far", "few",
    "find", "first", "for", "from", "get", "give", "goes", "going", "gone",
    "god", "gods", "good", "got", "great", "grow", "had", "has", "have",
    "having", "heaven", "hear",
    "held", "help", "her", "here", "hers", "him", "his", "hold", "how",
    "however", "hurry", "into", "its", "just", "keep", "kept", "know",
    "known", "last", "late", "later", "leave", "left", "less", "let", "like",
    "listen", "little", "live", "long", "look", "made", "make", "many", "may",
    "maybe", "mean", "might", "mine", "more", "most", "move", "much", "must",
    "near", "need", "never", "next", "nobody", "none", "nor", "not",
    "nothing", "now", "off", "often", "once", "one", "only", "onto", "open",
    "other", "others", "our", "ours", "out", "over", "own", "part", "people",
    "perhaps", "please", "point", "put", "quite", "rather", "read", "ready",
    "real", "really", "right", "run", "said", "same", "saw", "say", "see",
    "seem", "seen", "sent", "set", "shall", "she", "should", "show", "side",
    "since", "some", "someone", "something", "soon", "sorry", "stand",
    "start", "still", "stop", "such", "sure", "take", "tell", "than", "that",
    "the", "their", "them", "then", "there", "these", "they", "thing",
    "think", "this", "those", "though", "through", "time", "told", "too",
    "took", "toward", "try", "turn", "under", "until", "upon", "use", "very",
    "wait", "walk", "want", "was", "watch", "way", "well", "went", "were",
    "what", "when", "where", "whether", "which", "while", "who", "whole",
    "whom", "why", "will", "with", "within", "without", "wonder", "world",
    "would", "yes", "yet", "you", "your", "yours",
}


def observed_lowercase(texts) -> set:
    """Words the script itself uses in lower case somewhere.

    Free, chapter-specific evidence that a word is an ordinary word. If the
    English says "watch it grow" anywhere, then "Grow" at the start of a
    sentence is that verb and not the character - no hand-maintained word list
    could have known that, and this does."""
    import re as _re
    out = set()
    for t in (texts or []):
        for w in _re.findall(r"[A-Za-z]+", str(t or "")):
            if w.islower() and len(w) >= 3:
                out.add(w)
    return out


def canon_terms(ctx: "SeriesContext") -> dict:
    """canonical form -> the single spelling that is canon for it.

    People come from the character sheet, places and recurring terms from the
    glossary's English renderings. The sheet wins a collision: it is the thing
    the human edits by hand, so it is the more deliberate of the two."""
    import re as _re
    table: dict[str, str] = {}

    def add(word: str, override: bool) -> None:
        w = str(word or "").strip()
        if len(w) < 3 or not w[:1].isupper():
            return
        if w.lower() in _TITLE_WORDS or w.lower() in _COMMON_CAPS:
            return
        c = canon_name(w)
        if len(c) >= 2 and (override or c not in table):
            table[c] = w

    gl = getattr(ctx, "glossary", None) or {}
    for v in gl.values():
        for w in _re.findall(r"[A-Za-z]+", str(v or "")):
            add(w, False)
    for k in (getattr(ctx, "characters", None) or {}):
        for w in name_tokens(k):
            add(w, True)
    return table


def _near_term(canon: str, table: dict) -> str | None:
    """The canon term one edit away from this canonical form, if there is one.

    same_person refuses to match anything under five characters, because there
    it is deciding whether to MERGE two people and Mimi is not Momi. Here the
    only outcome is a note for a human to read, so the bar is lower: three
    characters, one edit. That difference is the whole reason this is not just
    a call to same_person - at the stricter bar, Aeda for Ada goes unremarked,
    and three-letter names are exactly the ones a reader skims past.

    One edit on two three-letter words is not a resemblance, though: it made
    "God" a near miss for "Glow". So at least one of the pair must be four
    characters or more, which is what separates Aeda/Ada from God/Glow."""
    if len(canon) < 3:
        return None
    import difflib
    for c, spelling in table.items():
        if c == canon or abs(len(c) - len(canon)) > 1 or len(c) < 3:
            continue
        if max(len(c), len(canon)) < 4:
            continue
        m = difflib.SequenceMatcher(None, canon, c)
        if (max(len(canon), len(c))
                - int(round(m.ratio() * (len(canon) + len(c)) / 2))) <= 1:
            return spelling
    return None


def enforce_spellings(text: str, table: dict, common=()) -> tuple:
    """Snap names and places back to the canon spelling. -> (text, notes).

    Two outcomes, deliberately different. A word whose canonical form IS a
    canon term is the same word wearing a different romanization - Leonore for
    Leonora - and is rewritten silently, because there is nothing to decide. A
    word that is merely NEAR a canon term is left exactly as written and
    reported instead: one edit apart can be a typo, but it can equally be
    Mimi and Momi, and a proofreader that quietly merges two characters is
    worse than one that asks."""
    import re as _re
    if not text or not table:
        return text, []
    common = set(common or ())
    notes: list[str] = []
    parts = _re.split(r"([A-Za-z]+)", str(text))

    for i in range(1, len(parts), 2):           # odd indices are the words
        w = parts[i]
        if len(w) < 3 or not w[:1].isupper():
            continue
        lw = w.lower()
        if lw in _COMMON_CAPS or lw in _TITLE_WORDS or lw in common:
            continue
        c = canon_name(w)
        if not c:
            continue
        canon = table.get(c)
        if canon:
            # SHOUTED lines keep their case: LEONORA stays LEONORA, it is not
            # quietly turned back into sentence case mid-yell.
            want = canon.upper() if w.isupper() and len(w) > 1 else canon
            if want != w:
                parts[i] = want
                notes.append(f"{w} -> {want}")
            continue
        near = _near_term(c, table)
        if near:
            notes.append(f'"{w}" is one letter from "{near}" '
                         "— same person, or a different one?")

    return "".join(parts), notes


def _ocr_context(page: "Page", ctx: "SeriesContext") -> str:
    """The reference the reader needs to resolve ambiguous glyphs: the names and
    terms this series already uses, and which regions are one split sentence.

    The split-line note is the important one. When a name runs across a bubble
    break - エー / ダ - a reader shown the halves with no warning tends to
    transcribe the whole name into one half and repeat it in the other."""
    bits: list[str] = []

    terms = [k for k in (getattr(ctx, "glossary", None) or {}) if str(k).strip()]
    if terms:
        gl = getattr(ctx, "glossary", {}) or {}
        bits.append("Terms already seen in this series, as printed -> how they "
                    "are rendered:\n"
                    + "\n".join(f"  {k} -> {gl[k]}" for k in terms[:60]))

    names = [str(k) for k in (getattr(ctx, "characters", None) or {}) if str(k).strip()]
    if names:
        bits.append("Characters in this series (English spellings; their names "
                    "appear in the page in the source script): "
                    + ", ".join(names[:40]))

    groups: dict[int, list[int]] = {}
    for r in page.regions:
        n = int(getattr(r, "link", 0) or 0)
        if n:
            groups.setdefault(n, []).append(r.id)
    joined = [g for g in groups.values() if len(g) > 1]
    if joined:
        bits.append(
            "These region groups belong together — either one sentence "
            "carried across boxes or two lobes of one drawn balloon: "
            + "; ".join("+".join(str(i) for i in g) for g in joined)
            + ". Transcribe each box with only the characters printed inside "
            "THAT box — if a word or a name is broken across the split, do not "
            "repeat the whole word in both halves and do not complete either "
            "half. A fragment like \"…エ\" is a correct answer.")

    return ("\n\n".join(bits) + "\n\n") if bits else ""


def read_page_ocr(page: Page, ctx: "SeriesContext", tiles, media_type: str = "image/png",
                  client=None, model: str = "", progress=None,
                  batch: int = 1) -> dict:
    """Vision OCR. Transcribe every region from the labelled page image(s).

    `tiles` is either raw PNG bytes for the whole page, or a list of
    (png bytes, [region ids]) pieces from ocr.page_label_tiles - one request per
    piece, so small typesetting arrives at something near its native resolution
    instead of being squashed into a whole-page thumbnail.

    Every request still carries the WHOLE page's region listing and the series'
    names and terms, so a piece is never read blind to the rest of the page.
    Returns {region_id: text}.
    """
    import base64
    regions = list(page.regions)
    if not regions:
        return {}
    if isinstance(tiles, (bytes, bytearray)):
        tiles = [(bytes(tiles), [r.id for r in regions])]
    tiles = [t for t in (tiles or []) if t and t[0]]
    if not tiles:
        return {}
    kind = "anthropic"
    if client is None:
        client, model, kind = make_client(
            backend=ctx.backend, base_url=ctx.base_url,
            model=ctx.model or MODEL, api_key=ctx.api_key,
            safety=getattr(ctx, "safety", "") or "",
            step_name=getattr(ctx, "step_name", "") or "")
    src = source_language(ctx.medium, ctx.source)
    system = build_ocr_system(src)
    order = sorted(regions, key=lambda r: getattr(r, "order", 0))
    listing = "\n".join(f"{r.id}: {r.kind}" for r in order)
    reference = _ocr_context(page, ctx)

    out: dict[int, str] = {}
    # How many pictures ride in one turn. One, unless the caller is sending a
    # crop per box - a dozen small pictures that all want the same system
    # prompt and the same page listing, and sending them separately would
    # multiply that text by a dozen and spend the whole saving.
    n_batch = max(1, int(batch or 1))
    if kind == "openai":
        n_batch = 1                      # that client takes one image a turn
    groups = [tiles[i:i + n_batch] for i in range(0, len(tiles), n_batch)]
    for n, group in enumerate(groups, 1):
        # Stop means stop -- between batches, which is the finest grain there
        # is here: a request already in flight cannot be unsent. See `stopping`.
        _stopping.check()
        if progress:
            try:
                progress(n, len(groups))
            except Exception:
                pass
        want = [i for _b, ids in group for i in ids] or [r.id for r in order]
        scope = (f"The page has these regions (id: kind), in reading order:\n"
                 f"{listing}\n\n")
        if len(group) > 1:
            scope += ("You are shown %d images from this page, one per region, "
                      "each blown up so its writing is legible. In order they "
                      "are the regions: %s. Each image has its own region "
                      "outlined in RED and numbered; anything grey in it "
                      "belongs to a neighbour. Transcribe ONLY those %d "
                      "regions.\n\n"
                      % (len(group), ", ".join(str(i) for i in want),
                         len(want)))
        elif len(tiles) > 1:
            scope += (f"This image is piece {n} of {len(groups)}, shown at higher "
                      "resolution than the full page. Transcribe ONLY these "
                      "regions, which are the ones outlined in red: "
                      + ", ".join(str(i) for i in want) + ".\n\n")
        user = (scope + reference
                + "Transcribe the text inside each numbered region and return "
                  "the JSON described.")
        b64 = [base64.b64encode(b).decode() for b, _ids in group]
        # A reply that is not JSON gets asked again, the way translating and
        # proofreading already do. This used to parse straight through, so ONE
        # malformed reply on ONE piece raised out of the whole run and took the
        # other 57 pages of the chapter with it. lee, reading a chapter a crop
        # per box: *"JSONDecodeError: Expecting property name enclosed in
        # double quotes"*. A crop per box is a dozen pictures in one turn and a
        # dozen entries in one reply, so there is more of it to get wrong.
        #
        # And when it STILL will not parse, the piece is skipped rather than
        # thrown: its regions come back unread, `do_ocr` flags them, and the
        # rest of the chapter finishes. A page you have to fix a box on beats a
        # run that stopped on page 12.
        data, why = None, ""
        for _try in range(OCR_TRIES):
            ask = user if not why else (
                user + "\n\nYour previous reply could not be read as JSON "
                f"({why}). Return ONLY the JSON object — no prose, no markdown "
                "fence, every key in double quotes, and every double quote "
                "inside a transcription escaped as \\\".")
            raw = _ask_vision(client, kind, model, system, ask,
                              b64 if len(b64) > 1 else b64[0], media_type)
            try:
                data = _extract_json(raw)
                break
            except Exception as e:
                why = str(e)[:120]
        if data is None:
            continue
        allowed = set(want)
        got: set[int] = set()
        for item in (data.get("regions") or []):
            try:
                rid = int(item["id"])
            except (KeyError, ValueError, TypeError):
                continue
            # A piece only speaks for its own regions; anything else it volunteers
            # was read off a greyed-out neighbour and belongs to another request.
            if rid not in allowed or rid in got:
                continue          # first answer per region wins, not the last
            got.add(rid)
            out[rid] = _unescape_breaks(str(item.get("text") or "").strip())
    return out


def _unescape_breaks(t: str) -> str:
    """A line break that arrived as two characters.

    Some models escape the newline twice on the way out - the JSON carries
    `"A\\nB"`, which parses to a backslash followed by an n, and the region
    then holds a literal `\n` where the line break should be. It is not
    consistent: in one 23-page chapter it happened on three pages and not on
    the other twenty, which is the worst kind of defect to notice by eye.

    Nothing in Japanese, Korean or Chinese typesetting is a backslash, so there
    is no reading of these two characters other than the one that went wrong.
    """
    if "\\" not in t:
        return t
    return (t.replace("\\r\\n", "\n").replace("\\n", "\n")
             .replace("\\r", "\n").replace("\\t", " "))


def translate_page(
    page: Page,
    ctx: Optional[SeriesContext] = None,
    client=None,
    model: str = MODEL,
    max_retries: int = 2,
    chapter: list | None = None,
) -> dict:
    """Fills dst_text / speaker on every region. Returns page_notes."""
    ctx = ctx or SeriesContext()
    payload = build_payload(page, ctx, chapter)
    if not payload["regions"]:
        return {}

    kind = "anthropic"
    if client is None:
        client, model, kind = make_client(
            backend=ctx.backend, base_url=ctx.base_url,
            model=ctx.model, api_key=ctx.api_key,
            safety=getattr(ctx, "safety", "") or "",
            step_name=getattr(ctx, "step_name", "") or "")
    elif isinstance(client, OpenAICompatClient):
        kind, model = "openai", client.model

    want = {r["id"] for r in payload["regions"]}
    last_err = ""

    for attempt in range(max_retries + 1):
        user = json.dumps(payload, ensure_ascii=False, indent=1) + "\n\n" + SCHEMA_HINT
        if last_err:
            user += f"\n\nYour previous reply was rejected: {last_err}. Fix it."
        # The head of it - the synopsis, the glossary and the chapter context -
        # is the same on every page of a run, so it is worth a tenth of the
        # price instead of all of it.
        fixed, _rest = split_at_the_fixed_part(user)

        # The reply is bounded at about twice its own prediction - the
        # unbounded half of the bill becomes a number we chose. Only on the
        # FIRST try: a retry after a truncated reply gets the full ceiling,
        # because the cap must never be the thing that truncated it twice.
        _cap = 8000
        if attempt == 0 and not last_err:
            from . import coins as _c
            _cap = _c.reply_cap("translate", len(payload.get("regions") or []),
                                sum(len(str(r.get("text") or ""))
                                    for r in (payload.get("regions") or [])),
                                model)
        text = _ask(client, kind, model,
                    build_system(ctx.medium, ctx.target,
                                 getattr(ctx, "source", ""),
                                 getattr(ctx, "honorifics", True)), user,
                    cache_prefix=fixed, max_tokens=_cap)

        try:
            data = _extract_json(text)
        except Exception as e:
            if _looks_truncated(text):
                last_err = ("your reply was cut off before the JSON ended — "
                            "answer tersely: keep page_notes empty and skip "
                            "optional additions")
            else:
                last_err = (f"invalid JSON ({e}) — escape every double quote "
                            "inside strings as \\\" and avoid raw line breaks")
            continue

        items = [it for it in (data.get("regions") or [])
                 if isinstance(it, dict)]
        try:
            got = {int(it["id"]) for it in items}
        except (KeyError, TypeError, ValueError):
            last_err = "every entry in regions needs a numeric id"
            continue
        if got != want:
            # Models occasionally drop or duplicate a region. Never let that pass
            # silently - a missing bubble is a blank bubble in the output.
            last_err = f"id mismatch: missing {sorted(want - got)}, extra {sorted(got - want)}"
            continue

        from .typeset import normalize_text
        by_id = {r.id: r for r in page.regions}
        for item in items:
            r = by_id[int(item["id"])]
            # normalize typographic characters at the door - comic fonts
            # can't draw most of them, and a tofu box in an export is worse
            # than a plain apostrophe
            r.dst_text = strip_added_lead(
                strip_added_ellipsis(
                    strip_added_dashes(
                        normalize_text(str(item.get("translation") or "").strip()),
                        r.src_text),
                    r.src_text),
                r.src_text)
            # THE NOTES ON THIS BOX ARE THIS RUN'S, and nobody else's.
            #
            # `flagged` arrives on the region carrying whatever the LAST run
            # put there - `region_from_record` loads it and everything below
            # used to append. So a box re-translated three times carried three
            # copies of the same remark, and lee's chapter 3 report proved it:
            # fourteen lines saying "about 9 characters for a balloon that
            # holds ~5 about 9 characters for a balloon that holds ~5", and
            # three sound effects still carrying a note from `half_a_sound`,
            # a check that had been deleted from the app entirely.
            #
            # The reading's own note is not lost: `looks_like_garbage` is a
            # pure function of the source text and the box, so asking it again
            # gives the same answer it gave at Read text. What is thrown away
            # is every remark about ENGLISH THAT NO LONGER EXISTS.
            # ...and the one thing about the box itself the reading can fix.
            # See `RETYPE_KINDS`: a shape cannot tell a drawn crash from a
            # muttered aside, and the words can.
            _retype(r, item, ctx)
            from .ocr import looks_like_garbage
            r.flagged = looks_like_garbage(r.src_text, r) or ""
            if added_masking(r.dst_text, r.src_text):
                r.flagged = (r.flagged or "") + " " + CENSOR_NOTE
            # ...and the two the last chapter needed: a shout cut down to one
            # mark, and a line the balloon will not hold.
            note = (quieter(r.dst_text, r.src_text)
                    or stops_short(r.dst_text, r.src_text)
                    or too_long(r.dst_text, r,
                                getattr(ctx, "min_font", 12)))
            if note:
                r.flagged = ((r.flagged or "") + " " + note).strip()
            # Who said it, unless nobody asked for that. A speaker the
            # model was told not to return but returned anyway is still
            # dropped here - the switch is about the SHEET's contents, and a
            # rule enforced only by asking politely is not enforced.
            sp = item.get("speaker") if getattr(ctx, "name_speakers", True) else None
            r.speaker = str(sp) if sp not in (None, "") else None
            try:
                r.confidence = float(item.get("confidence") or 0.0)
            except (TypeError, ValueError):
                r.confidence = 0.0
            if r.confidence < 0.5:
                r.flagged = (r.flagged or "") + " low translation confidence"

        # ...and now the whole page is in, which is when a LINK can be looked
        # at: the rule is about where the dots sit across two boxes, so it
        # cannot be decided one region at a time. See `fix_linked_tails`.
        fix_linked_tails(page.regions)

        story = getattr(ctx, "story", True)
        gl = data.get("glossary_additions") or {}
        if story and getattr(ctx, "learn_terms", True) and isinstance(gl, dict):
            # Every term must say what it is - see `merge_glossary`. A bare
            # name comes back refused, and is shown the same way a refused
            # character is.
            gl_refused = merge_glossary(ctx.glossary, gl,
                                        getattr(ctx, "characters", None))
            if gl_refused:
                data["glossary_refused"] = gl_refused

        # What this page actually writes down, plus everything established
        # before it. Built AFTER the translations land, because a character is
        # usually named by somebody addressing them on this very page.
        evidence = name_evidence(
            ctx, [r.dst_text or "" for r in page.regions]
            + [r.src_text or "" for r in page.regions])

        # Two passes over the speakers, in this order and not the other:
        #   1. someone already on the sheet, spelled loosely, is snapped back to
        #      the sheet's spelling - otherwise "Glou" and "Glow" drift apart
        #      page by page. This has to run unconditionally: the sheet is part
        #      of the evidence, so a loose spelling of a known name looks
        #      perfectly well-evidenced and would never reach step 2.
        #   2. whatever is left and is written nowhere at all was invented. Keep
        #      the label - it may still be the right person - but say so, so it
        #      is not mistaken for something the page established.
        for r in page.regions:
            # Nothing to snap a name back TO when the sheet is switched off,
            # and "is not named anywhere" is a complaint about a sheet nobody
            # is keeping. Both checks read the character sheet; when there is
            # no character sheet there is no check.
            if not story or not r.speaker or is_generic_speaker(r.speaker):
                continue
            known = match_known(r.speaker, getattr(ctx, "characters", {}) or {})
            if known:
                r.speaker = known               # a known face, spelled loosely
                continue
            if unevidenced(r.speaker, evidence):
                r.flagged = ((r.flagged or "")
                             + f" speaker \"{r.speaker}\" is not named anywhere"
                             ).strip()

        # ...and the same question asked of the PROSE, which is where lee's
        # Chrysos/Chryses happened - in the body of two narration boxes, four
        # pages apart, with no speaker and no glossary term anywhere near it.
        #
        # NOT gated on the story switch: this is about one chapter agreeing
        # with itself, not about a sheet anybody is keeping, and `already_said`
        # travels whether the sheets do or not. Reads `names_seen` BEFORE
        # `remember_said` adds this page to it, so a name is never a near-miss
        # of itself.
        was_said = list(getattr(ctx, "names_seen", None) or [])
        for r in page.ordered():
            for was, now in name_drift(was_said, names_in(r.dst_text or "")):
                r.flagged = ((r.flagged or "")
                             + f" \"{now}\" was \"{was}\" earlier in this"
                               " chapter").strip()

        adds = data.get("character_additions") or {}
        if story and getattr(ctx, "learn_characters", True) and isinstance(adds, dict):
            # first sighting wins: the sheet is canon, later pages only extend
            # it - they must not flip someone's pronouns, nor spell them a
            # second way, nor add a name the story never wrote down
            refused = merge_characters(ctx.characters, adds, evidence,
                                       is_generic_speaker)
            if refused:
                data["characters_refused"] = refused
        # the tail carries WHO said each line, so the next page starts with
        # the speakers straight instead of re-guessing them
        ctx.previous_page_tail = [
            (f"{r.speaker}: {r.dst_text}" if r.speaker else r.dst_text)
            for r in page.ordered() if r.dst_text
        ][-6:]
        # ...and who and what this chapter has now called things. Unlike the
        # tail, this does not fall off after six lines: page 57 has to be able
        # to see what page 46 called the grandfather.
        remember_said(ctx, page, data.get("glossary_additions") or {})
        return data

    raise RuntimeError(f"translation failed after {max_retries + 1} attempts: {last_err}")
