# Every feature of MangaTCT

A reference, not a tutorial. Everything the editor can do, arranged the way you
meet it: the window first, then the settings, then what each of the seven steps
really does, then the money.

Written against the code on 7 August 2026. Where a number appears in here it is
the number in the source, named so you can go and check it. Where the code and
this page disagree, the code is right and this page is a bug.

Three conventions:

* **Exact labels are in bold.** If it is bold, that is the text on screen.
* `Monospace` is a settings key, a file, a function or a route.
* A **family** is one of the three kinds of box (bubble, outside text, sound
  effect). A **sub-type** is a named variety within a family. The distinction
  runs through everything and is explained under Box types.

---

## Contents

1. [The window](#1-the-window)
2. [Menus and dialogs](#2-menus-and-dialogs)
3. [Keyboard shortcuts](#3-keyboard-shortcuts)
4. [Settings, field by field](#4-settings-field-by-field)
5. [Box types](#5-box-types)
6. [Reading order](#6-reading-order)
7. [The seven steps, inside](#7-the-seven-steps-inside)
8. [Webtoon strips](#8-webtoon-strips)
9. [Accounts and coins](#9-accounts-and-coins)
10. [Files](#10-files)
11. [Things that are not there](#11-things-that-are-not-there)

---

# 1. The window

Three bars stacked, then one row.

| Part | id | When it is there |
|---|---|---|
| Top bar | `#top` | Always |
| Step bar | `#work` | Workspace tab only |
| Main row | `#main` | Always |

The main row holds, left to right: the page list `#pages` (168px, hidden on
Settings and File), the reference pane `#refWrap` (only with Side by side on),
the tool column `#toolbox` (40px, Workspace + Image view only), the canvas, and
the right panel `#side` (330px, Workspace only).

**A naming trap worth knowing before anything else.** The view pill says
**Translation** and **Image**. Internally those are `original` and `typeset`.
There is a third view, `clean`, with working code behind it and no control
anywhere that reaches it.

## 1.1 The four tabs

| Label | id | What it is |
|---|---|---|
| **File** | `tabNew` | Start a project, save it, open one, import or export story context |
| **Workspace** | `tabEdit` | The editor. Starts selected |
| **Results** | `tabRes` | The exported pages |
| **Settings** | `tabSet` | Everything configurable |

Workspace and Results are never greyed out in the ordinary sense. When they are
not usable they take the click anyway and say why:

* Workspace with no pages: *"Nothing to work on yet - add pages on the File tab
  first."*
* Results with nothing exported: *"Nothing exported yet - finish a page and
  press Export on the Workspace tab, and the results appear here."*

A tab switched by code rather than by a click redirects silently instead.

## 1.2 The top bar

**Left:** the wordmark (a link to `/`), then the four tabs.

**Middle right: the coin button** (`#coinBtn`). The TCT coin and a count.
Present on every tab. Clicking it opens the purse. The count starts as an em
rule and is filled by `/api/coins`. Two states:

| State | When | Look |
|---|---|---|
| `.broke` | balance ≤ 0 | red |
| `.low` | 0 < balance < the price of this whole chapter | amber |

"Low" is therefore *"less than one more chapter at today's models"*, not a
fixed number. A hundred coins is plenty for Gemini and nothing at all for Opus.

**Right, on the Results tab** (`#resultTools`):

| Label | Does |
|---|---|
| **Start a new project** | Confirms, then `/api/reset`, keeping the technical settings |
| **Download story context** | Writes `<series>.tct` |
| **Download all as .zip** | `/api/export_zip`, saved as `translated-pages.zip` |

**Right, on the Workspace tab** (`#pageTools`), in order:

| # | Label | Does |
|---|---|---|
| 1 | **&minus;** | Zoom out 5 percentage points, snapped to a 5% grid, clamped 5-800% |
| 2 | **100%** (live) | Click to fit the page in the window. The number is the real page-pixel to screen-pixel scale |
| 3 | **+** | Zoom in 5 points |
| 4 | **Hide boxes** | Hides the outlines. Ticked automatically on the way *into* the Image view; your previous state is put back on the way out |
| 5 | **Side by side** | Shows the untouched original beside the page, same zoom, scroll-linked. Only appears on Workspace + Image |
| 6 | **Translated text** | Shows or hides the typeset English. Only appears in the Image view. Disabled until something has actually been laid out, with the reason in its tooltip |
| 7 | **Translation** | The boxes and the region list |
| 8 | **Image** | Typesetting and painting |

Items 5 and 6 sit before the view pill deliberately: switches that come and go
would otherwise shove the pill under your pointer.

## 1.3 The step bar

Left: the seven steps. Right: the job.

| Control | Behaviour |
|---|---|
| Status text | **Ready**, or *"`<step>`… `n` of `m` pages (`p`%)"*. Four states: error, busy, warning, idle. Click it to toast the full text when there is more than fits |
| Progress bar | The job percentage. 0 on error, 100 otherwise |
| **Cancel** | Only while a job runs. Becomes **Stopping…** |
| Queue button | A clock and a count. Start something while another action runs and it lines up here |

### The seven steps

**TRANSLATION**

| # | Label | Opens |
|---|---|---|
| 1 | **Find text** | The "What should I look for?" dialog |
| 2 | **Read text** | The scoped-run dialog |
| 3 | **Translate** | The scoped-run dialog, with the by-hand extras |
| 4 | **Proofread** | The scoped-run dialog, with the report extras |

**IMAGE**

| # | Label | Opens |
|---|---|---|
| 5 | **Clean** | The scoped-run dialog |
| 6 | **Typeset** | The scoped-run dialog |

**EXPORT**

| # | Label | Opens |
|---|---|---|
| 7 | **Export** | The export dialog |

Each button carries the step number (a tick when finished), the label, a
`done/total` count and a 2px fill bar.

**The denominator is the ticked pages in the left rail.** If nothing is ticked
it falls back to every page.

**Done, per page:** step 1 = the page has been looked at; steps 2, 3 and 4 =
the read / translated / proofread count has reached the region count; step 5 =
cleaned, or using your own cleaned plate; step 6 = the typeset count has reached
the region count; step 7 = exported. A ticked page with **no text on it** passes
every text step, so a chapter of splash pages does not stall the counter at
26/30.

**Every step can be run at any time, in any order.** There are no locks. The
only refusal is that with **I'll translate it myself** on, steps 2, 3 and 4 are
greyed and do nothing.

## 1.4 The page list

| Control | Does |
|---|---|
| **+ Add pages** | Picks image files. Not shown on the Results tab |
| **Select all (n/m)** / **Deselect all** | Ticks or unticks everything. The label only flips to Deselect when every page is ticked |

Each row, left to right:

1. **A checkbox** - tick to include in "do all". Keyed by page **name**, not
   position, and remembered in the browser. A page it has never seen starts
   ticked.
2. **Dots** - one per step of the view you are in: 4 in the Translation view
   (Find, Read, Translate, Proofread), 2 in the Image view (Clean, Typeset).
   Green when that step is done for that page. Each dot names its step in a
   tooltip.
3. **The name.**
4. **A small number** - how many text boxes are on that page. Blank at zero.
5. **×** on hover - takes the page out of the project. It does not delete the
   file. Removing the last page reopens the File screen.

**Reordering** is drag and drop, with a line showing where it will land. The
move happens locally at once and is rolled back if the server refuses.

**Right-click a row** for **Rename…**, which turns the name into a field in
place. The extension is stripped for editing and put back by the server.

## 1.5 The tool column

Workspace tab, Image view only. Photoshop-style slots: each slot shows the tool
last used out of it, and a corner triangle marks a slot with more than one.
Right-click or press and hold for 420ms to open the flyout. Exactly one tool is
armed at a time.

| Slot | Tool | Name on screen | Key |
|---|---|---|---|
| Move | Free transform | **Free transform (T)** - corners move freely | T |
| Move | Scale and rotate | **Scale and rotate** | |
| Select | Rectangle | **Rectangular select (M)** | M |
| Select | Lasso | **Lasso (L)** | L |
| Select | Wand | **Magic wand (W)** | W |
| Text | Add text | **Add a text box** - your own words, not a translation | |
| Paint | Brush | **Brush (B)** | see note |
| Paint | Eraser | **Eraser (E)** | E |
| Fill | Bucket | **Bucket fill (G)** | G |
| Retouch | Clone stamp | **Clone stamp** | |
| Retouch | Healing | **Healing brush** - the AI redraw one | |
| Shape | Rectangle | **Rectangle** | |
| Shape | Ellipse | **Ellipse** | |
| Shape | Line | **Line** | |
| Pick | Eyedropper | **Eyedropper (I)** - native picker where the browser has one, else click-to-sample with a loupe | see note |
| View | Hand | **Hand (H)** - double-click for actual size | H |
| View | Zoom in | **Zoom in** - click to zoom, Alt inverts | |
| View | Zoom out | **Zoom out** | |

**Note.** The brush and eyedropper labels advertise B and I. No handler binds
either key; B is taken by **Hide boxes**. Every other letter on that list works.

## 1.6 The right panel

| Region | What it holds |
|---|---|
| Colour key | One chip per family, numbered 1/2/3 for their shortcut keys, plus a dashed "unsure" chip. Sub-types are deliberately not listed here |
| Inspector | Changes with the view - see below |
| **I'll translate it myself** | The switch, and under it **Template (TXT)**, **JSON** and **Upload filled in…**. It lived in Settings for a while; lee: *"move teh ill translate myselt to the translation tab"* |
| **Text on this page** | The heading, hidden in the Image view |
| Proofreader note | An orange card, when the page has one. Carries clickable box numbers for everything the proofreader changed |
| Region list | One row per box in reading order. Hidden in the Image view |
| **History - this session** | The last 40 things you did, with times. Fresh on reload |
| Shortcut hint | `Del` remove · `S` mark as SFX · `L` link to another bubble · `←` `→` pages |

**A region row** carries: the order number (drag it to renumber), a confidence
chip (green at 0.55 and above, red below, absent on your own boxes), the type
chip with its colour dot, a link chip, and an eye that hides that one box.
Below: the English, then the Japanese, with "not translated" and "no text read"
where either is missing.

**Selecting a row opens it in place** into: Main type, Sub-type, the Japanese
and the English as editable fields, and **Split**, **Delete**, and **Link…** /
**Link to next** or **Unlink**.

### The inspector, by view

**Translation view - Current page.** The name, "n of m", a count of text boxes
and how many are hidden, whether it is cleaned, and a **SHOW OR HIDE** block of
per-family switches, plus **Apply to every page in the chapter**. Only families
actually present are listed.

**Image view, nothing selected - the cleaning panel.**

* **Cleaning per bubble** - one row per box naming the route it took: *filled
  flat*, *by the AI*, *locally*, *tone copied*, *AI would not run*. Each has an
  eye that puts the original pixels back for that box alone. The whole card is
  omitted when the page is using your own cleaned plate.
* **Cleaned plate** - **Use my own cleaned page…** / **Back to automatic**.
* **Tool settings** - Tolerance, Filled / Outline plus Deselect, the shape list,
  the brush colour well and eyedropper, Size, Opacity, Hardness.
* **Layers.**

**Image view, a box selected - Typesetting.** An "edited" chip appears when the
layout is locked. Main type and Sub-type, a flag chip for layout problems, and
four groups, all open:

| Group | Controls |
|---|---|
| Paragraph | Alignment, Line gap, Letter gap, ALL CAPS |
| Character | Font, Size, Rotation, Outline, Curve |
| Colour | Text colour, Outline colour, Gradient from/to/angle, Outline gradient from/to/angle, Opacity |
| Effects | Shadow + Dist + Blur, Outer glow + Size, Inner glow + Size |

A box with no layout yet says so and offers to lay the page out.

---

# 2. Menus and dialogs

## 2.1 The File screen

A full-screen overlay with its own rail.

| Section | Items |
|---|---|
| File | **New project**, **Project file** |
| This chapter | **Save project**, **Save as…**, **Open project…** |
| This series | **Download story context**, **Import story context…** |

**New project** is a two-step wizard. *1 · Pages*: the medium, source language,
direction and target menus, a drop zone, **Add pages from a folder…** and **Add
pages…**, the staged list with **Clear all**. *2 · Story context*: drop or
choose a `.tct`, then **Done** (only enabled after an import) or **Skip**.

## 2.2 The run dialog

Opened by steps 2 to 6. The title changes per step: **Read the Japanese?**,
**Translate?**, **Proofread?**, **Clean the pages?**, **Lay the text out?**

| Button | Notes |
|---|---|
| **Every page (n)** / **Selected pages (n)** | The price in coins sits on the button. A free step shows no price at all |
| **This page only** | Its own price |
| **Cancel** | |

**Translate** adds three: **Download the AI request (.json)**, **Add the AI's
reply…**, **Export translated text (.json)**.

**Proofread** adds **Download the proofread report (.md)**, offered before a run
as well as after one.

## 2.3 The other dialogs

| Name | For |
|---|---|
| **What should I look for?** | Find text. **Speech and narration bubbles** (ticked), **Text outside bubbles**, **Sound effects**, then **Find on every page** / **This page only** / **Cancel**. Refuses with a toast if nothing is ticked |
| **Add the AI's reply** | Paste or upload the translation JSON |
| **Export the translated pages** | See Export, below |
| Confirm | Used by **Start a new project?** and **Remove `<page>`?** |

## 2.4 The popovers

| Name | Contents |
|---|---|
| The purse | The balance; the account row; **This chapter, all N pages** with a row per paid step and an **Everything** total; a note about per-box pricing; a warning naming any unpriced model; **Buy coins**. Deliberately no ledger and no dollar figure |
| Queue | The running action with **Stop**, then each waiting action with ▲ sooner, ▼ later, × drop |
| Toolbox flyout | The other tools in a slot |
| Page menu | **Rename…** |
| Colour picker | SV square, hue strip, hex field, eyedropper, recent colours |
| Loupe | The magnified pixel while sampling, when the browser has no native picker |
| On-canvas text editor | Sits exactly on the text frame. Escape discards, Ctrl/Cmd+Enter commits, clicking away commits |

---

# 3. Keyboard shortcuts

| Key | Does | Where |
|---|---|---|
| `←` `→` | Previous / next page | Anywhere but a text field |
| `Delete` `Backspace` | Delete the selected paint layer if one is picked, else the selected box(es) | Anywhere but a text field |
| `1` `2` `3` | Set the box to family 1, 2 or 3 | Translation view, a box selected |
| `4`-`8` | Set the box to the 4th-8th sub-type **of the family it is already in** | Translation view, a box selected |
| `S` | Mark the box as SFX | A box selected |
| `L` | Link mode: the next box you click joins to this one | A box selected |
| `H` | Hand tool | Anywhere |
| `B` | Toggle **Hide boxes** | Anywhere |
| `+` `=` | Zoom in ×1.25 | Anywhere |
| `-` | Zoom out ÷1.25 | Anywhere |
| `0` | Fit the page | Anywhere |
| `[` `]` | Brush size down / up | While a paint tool is armed |
| `Escape` | Put the zoom tool away, else clear the selection, else cancel link mode, else close a flyout or menu | Anywhere |
| Hold `C` | Clicks add to the selection instead of replacing it | Anywhere but a text field |
| Hold `Ctrl`/`Cmd` | The same, and the click carries the modifier | Anywhere |
| `Alt` + digits, release `Alt` | Renumber the box to that position. Alt+1+2 is #12. Up to three digits; 0 and out of range are refused | Translation view, a box selected |
| `Ctrl`/`Cmd`+`Z` | Undo | Anywhere but a text field |
| `Enter` | Apply the free transform | While one is active, even from a field |
| `Escape` | Cancel the free transform | While one is active |
| `Ctrl`/`Cmd`+`D` | Deselect the marching ants | Image view |
| `Ctrl`/`Cmd`+`C` | Copy the selection | Image view, a mask exists |
| `Ctrl`/`Cmd`+`V` | Paste - a system clipboard image becomes a new layer in free transform, falling back to the in-app copy | Image view |
| `M` `L` `W` `G` `E` | Rectangle, lasso, wand, fill, eraser | Image view |
| `T` | Free transform | Image view |
| `V` | The shape arrow | Image view |
| `J` | Lift the selection to its own layer | Image view |
| `←↑→↓` | Extend the stroke 1px | While a stroke is held |
| `Shift` + arrows | Stride 8px | While a stroke is held |
| Hold `Shift` | Constrain to a square, a circle, or one of eight line directions | While drawing a shape |
| `Escape` | Discard the on-canvas text edit | In the text editor |
| `Ctrl`/`Cmd`+`Enter` | Commit the text edit | In the text editor |

`L` is bound twice in the Image view - link mode and the lasso - and neither
stops the other.

---

# 4. Settings, field by field

The Settings tab is a full screen with its own rail. **Every field saves the
moment you change it.** The footer's **Save settings** only takes a fresh
snapshot and leaves; **Cancel** puts the snapshot taken on the way in back.

The rail, in order:

| Group | Buttons |
|---|---|
| **Story** | **Story settings**, **Synopsis**, **Characters**, **Places, terms & other** |
| **Settings** | **Fonts & typesetting**, **Language & direction**, **Detection & OCR**, **Translation engine**, **Page cleaning** |

It opens showing **Synopsis**, with **Story settings** highlighted in the rail.
Nothing calls the tab switcher on the way in, so the highlight and the section
disagree on the first visit.

## 4.1 Story ▸ Story settings

The section the story lives or dies by. lee: *"add a story setting that allow
the user ti turn the story thing off, and to tun what the ai detects with check
boxes"*.

> The synopsis, the character sheet and the glossary are what keep chapter 4
> calling her the same thing chapter 3 did. They travel with every page, and the
> AI adds to them as it reads. Some projects want none of that: a one-shot, a
> gag strip, a script somebody else already wrote.

| Label | Key | Default | What it changes |
|---|---|---|---|
| **Keep a story for this project** | `story` | on | The master. Off, nothing from Synopsis, Characters or Places & terms is sent to the model, and nothing is added to them |
| **Add characters it meets to the sheet** | `learn_characters` | on | Whether the reply may put a new character on the sheet |
| **Add places, terms and other proper nouns to the glossary** | `learn_terms` | on | Whether the reply may put a new term in the glossary |
| **Name who is speaking each line** | `name_speakers` | on | Whether a speaker is asked for at all |

Under the three: *"Each one on its own. A series with a big cast wants the
character sheet and not the glossary; somebody working from a script wants the
words and no speaker guessed at all."*

**Off does not delete anything.** *"What you have written stays on disk."* Turn
it back on and the sheets are exactly as they were, which is the difference
between a switch and a delete.

### How it is enforced

Two ways, and the second is the one that matters.

**The model is told.** A `do_not_return` list goes into the payload, in the
fixed half so the cache is unaffected, naming the fields it must leave out of
its reply entirely. With the master off, the synopsis, the glossary and the
character sheet are **not sent at all** - and the prompt says what that means:
*"A field you were not given is one nobody is keeping for this project."*

**And the reply is filtered anyway.** Asking is not enforcing:

* the speaker is discarded when **Name who is speaking** is off;
* the glossary merge only runs with the master **and** **Add places, terms** on;
* the character merge only runs with the master **and** **Add characters** on;
* both speaker passes - the snap to the sheet's spelling and the "not named
  anywhere" flag - are skipped entirely when the master is off.

### What the switches do not reach

**Read text** still sends up to 60 glossary terms and 40 character names, to
settle uncertain glyphs. **Proofread** still sends the synopsis, the glossary and
the character sheet, and still snaps speakers to the sheet. Both are checks
against what you have written rather than additions to it.

With the master off, the three story buttons in the rail are dimmed and the
three sub-switches are faded and disabled, with their own values untouched.

## 4.2 Story ▸ Synopsis

| Label | Key | Type | Default | What it changes |
|---|---|---|---|---|
| Title | `title` | text, 120 max | empty | Names the series. Used for the `.tctp` and `.tct` filenames. **Not sent to any model** |
| Series synopsis (guides the translation) | `synopsis` | textarea, grows to 10 lines | empty | Sent verbatim with every translate and proofread request. The prompt treats it as ground truth and forbids contradicting it. Not sent to the reader |

## 4.3 Story ▸ Characters

A list of rows, each **Name** plus **pronouns · how they speak**, an **Add**
row, and a × per row.

A character has exactly two fields: the name, which is the canonical spelling,
and a note that begins with pronouns and continues with how they talk.

Saving **replaces the sheet outright**. The human is the authority; nothing the
AI proposed survives an edit you did not make.

## 4.4 Story ▸ Places, terms & other

Rows of **how it should be written in English** plus **a short note - what or
where it is**, an **Add** row, and a × per row.

Stored as `source term → "Rendering (note)"`. An entry whose rendering matches
a character's name is hidden from this list and still sent, so a person does
not appear in two places.

**An entry with no note is refused**, including one the AI proposes. "Tarel"
tells a translator nothing; "Tarel (the copper coin)" does.

## 4.5 Settings ▸ Fonts & typesetting

| Label | Key | Type | Default | What it changes |
|---|---|---|---|---|
| Min pt | `min_font` | number | 12 | The floor of the automatic size sweep. Below it a box is flagged rather than shrunk |
| Max pt | `max_font` | number | 34 | The ceiling the sweep starts from |
| Let the typesetter substitute glyphs | `substitutes` | checkbox | **on** in the page, **off** in the typesetting config's own default | On: a character the face cannot draw may be swapped, or the block may fall through to another face, and the substitution is flagged. Off: the character is kept and the box is flagged instead |
| Add fonts… | - | file, .ttf/.otf, multiple | - | Installs into `~/.mangatl/fonts`, outside every project, so the next chapter already has them. Each has a × |

**Box types.** One row per family - **Regular speech**, **Outside text**,
**Sound effect** - setting that family's default face. Then one row per
sub-type: a colour swatch you click to cycle, the name (editable), a font menu
where empty means "inherit the family's", and a ×.

**The add row** takes a family, a name and a font. Ten sub-types per family
maximum, on top of the undeletable default.

Two hidden fields survive from older versions: `font` (the project default
face, now edited through the Regular speech row) and `uppercase`, kept only so
a project that had it on keeps it. Capitals are a per-block decision now.

## 4.6 Settings ▸ Language & direction

| Label | Key | Type | Default | Options | What it changes |
|---|---|---|---|---|---|
| Source material | `medium` | menu | `manga` | manga, manhwa, manhua | The prompt's medium. **Changing it refills the next two**: manga → Japanese, right to left; manhwa → Korean, left to right; manhua → Chinese, left to right |
| Re-cut webtoon strips when a chapter is loaded | `restitch_strips` | checkbox | **on** | | A sliced webtoon is re-joined and cut at the gutters on upload. Skipped entirely if any page already has work on it |
| Page height | `strip_target` | number, min 600 | 2400 | | The page height the re-cut aims for |
| Never taller than | `strip_max` | number, min 1000 | 6000 | | The ceiling. Past it the page is cut at the quietest row and reported |
| Reading direction | `direction` | menu | `rtl` | rtl, ltr | The order boxes and pages are read in |
| Written in | `source` | menu | `ja` | ja, ko, zh, en, es, pt, fr | The source language for reading and for the prompts |
| Translate into | `target` | menu | `en` | en, es, pt, fr | The target language |

## 4.7 Settings ▸ Detection & OCR

| Label | Key | Type | Default | Options | What it changes |
|---|---|---|---|---|---|
| Reading detail | `ocr_detail` | menu | `auto` | **Whole page at once** (1 request a page), **Cut the page up** (up to 4), **Finest** (up to 9) | How many labelled tiles the page is cut into before the vision reader sees it. Each tile is one billed request |
| Text detector | `detector` | menu, one option | `comictext` | comic-text-detector | Which box finder runs |
| Model path | `weights` | text | empty | | The detector's weights file. Empty falls back to the classical detector |
| Label box types | `auto_kind` | checkbox | **on** | | Each found block is labelled by family rather than all being called a bubble |
| Text model path (optional) | `text_weights` | text | empty | | Only used by the legacy hybrid detector |

**One dead label.** *"Text reader (OCR)"* has no control under it. The menu was
removed and the label was not, and the save routine still posts `ocr_engine:
'ai'` unconditionally because the element is missing. Harmless today - the
editor's reader is always the vision model - but it overwrites the stored
default on every save.

## 4.8 Settings ▸ Translation engine

Three blocks: **API KEYS**, then **THE MODEL FOR EACH STEP**, then the safety
switch. There are no per-control labels inside a step, only one heading over
the row: **READ TEXT - the model that reads the page**, **TRANSLATE - the model
that writes the English**, **PROOFREAD - the model that checks it**.

| Label | Key | Type | Default | What it changes |
|---|---|---|---|---|
| Claude API | `key_anthropic` | password | empty | One key per service, not one per step |
| Google AI Studio | `key_gemini` | password | empty | |
| OpenRouter | `key_openrouter` | password | empty | |
| (read) provider | `ocr_backend` | menu | `gemini` | Claude API, Google AI Studio, OpenRouter |
| (read) provider within it | - | menu, usually hidden | - | The **vendor** menu. See below |
| (read) model | `ocr_model` | menu, written to a hidden field | `gemini-3.5-flash-lite` | Vision-capable models only |
| (read) address | `ocr_base_url` | text, no label, placeholder *"address, only for a local or odd one"* | empty | Only for a local or unusual endpoint |
| TRANSLATE provider / model / address | `translate_backend` / `translate_model` / `translate_base_url` | | `gemini` / `gemini-3.6-flash` / empty | |
| PROOFREAD provider / model / address | `proofread_backend` / `proofread_model` / `proofread_base_url` | | `anthropic` / `claude-sonnet-5` / empty | |
| Turn Gemini's safety thresholds down | `gemini_safety_off` | checkbox | off | Sets Google's four configurable categories to OFF. Core protections are unchanged |

**Where keys are stored.** In the project's own `project.json`, in plain text,
and therefore inside any `.tctp` you hand to somebody. The File screen says so.
They are never sent back to the browser - a key that is set reads as the word
"set".

### The vendor menu

A reseller's list is a hundred models from a dozen makers, and picking one out
of a flat list of that is not a choice, it is a search. So when the ids carry a
maker, a second menu appears between the provider and the model listing the
makers - `google`, `anthropic`, `deepseek` - plus **All providers**.

It appears **only when the list holds more than one maker**, which in practice
means OpenRouter: a direct service returns bare ids with no maker in them.

It is a **pure filter**. Changing it re-draws the model menu from what was
already fetched: no request, and **nothing is saved**. Browsing makers never
changes what a step runs on. Models with no maker in their id are always kept,
because those are a direct service's own ids and hiding them would make them
unreachable.

### How the model menu is built

The list is the **intersection** of what this app can offer and what your key
can actually **reach**, asked of the provider live. An empty intersection falls
back to the offered list.

Seven rules cut it down:

1. **A variant suffix** in the id - `:free`, `:nitro`, `:floor` - is refused on
   anything but a local provider.
2. **Anything not priced**, and anything **retired**: still priced so old
   projects keep working, never offered. Twelve of them - the Claude 4 family,
   the older Haikus, the Gemini 2.0 pair, and the whole GPT-4 family.
3. **Blind models, for Read text only.** A model that cannot see, chosen to read
   a page, is a 404 one step later.
4. **Anything that is not a translator at all** - text to speech, image
   generation, video, embeddings, reranking, moderation, transcription, realtime
   and computer use.
5. **Anything unsettled** - preview, experimental, beta, alpha.
6. **Anything more than one generation behind** the newest of its own family.
7. **On OpenRouter, anything your other keys can already reach directly.** lee:
   *"exclue teh model that are usabe with teh keys that i have"* - if your Google
   key can call it, it does not need to be on the OpenRouter list too.

Then **one per price**: models sharing an identical rate collapse to the newest
of them. What is left is a short list where every entry costs something
different from every other.

**A provider this app has no prices for** shows nothing, because "not priced"
is rule 2. The only exception is a local or free backend, where everything is
priced at zero and rules 1, 4, 5 and 6 are skipped entirely.

The answer is cached for 15 minutes per address and key, with a 6 second
timeout, and thrown away the moment a key or an address is edited.

A model that is set but no longer offered is kept in the menu as
**`<name>` - as set**. One that is offered but has no price reads **- not
priced**. An empty list says **No models - check the key for this service**.
There is no free-text box: the menu is the only way to set a model.

## 4.9 Settings ▸ Page cleaning

| Label | Key | Type | Default | Options |
|---|---|---|---|---|
| Method | `ai_clean` | menu | `off` | **Local - instant, no cost (default)**, **AI for hard areas** (screentone, SFX, text on art), **AI for the whole page** |
| Cleaner endpoint URL | `clean_url` | text | empty | |
| Cleaner token | `clean_token` | password | empty | Shown as "set", or in red as "placeholder" if it is still the example value |
| Test cleaner | button | | | One real call, and the answer in words |

## 4.10 Settings with no control

`compact_margin` 0.60; `export_dir`, `export_name` "pages", `project_file`,
`exported`, `hide_all_pages`, `custom_kinds`, `kinds_seeded`,
`kinds_seeded_keys`, and a set of legacy single-engine keys that are read as
fallbacks and never written.

`gemini_safety_off` is not in the defaults at all: it only exists once the
browser has saved settings, and an absent value is off.

One more worth knowing: **`honorifics` is on and has no switch.** It is sent
with every translation as `keep_honorifics`. It can only be changed by editing
`project.json` or importing a `.tct` that carries a different value.

## 4.11 I'll translate it myself

**Not in Settings.** The switch is in the Workspace right panel, under the
inspector. It spent a while in Settings; lee: *"move teh ill translate myselt to
the translation tab"*. It is documented here because it is a setting in
everything but position.

Switching it on greys the three AI text steps and reveals a row with:

* **Template (TXT)** and **JSON** - downloads every box, numbered the way the
  box sheet numbers it, with the original beside each one and room to type.
* **Upload filled in…** - takes `.txt`, `.json` or `.md` back.

The format is one block per box: `[<page name> #<n>]  <source text>`, with the
English typed on the following lines. An empty block leaves that box alone. Two
lines stay two lines. Whatever comes in wins.

It is a mode, not a lock: nothing on the server refuses those steps, and turning
it off restores them at once.

---

# 5. Box types

**Three families. Every box is in exactly one.** A family is a grouping and has
no colour of its own. What a box *is* is a **sub-type**, and the sub-type
carries the colour.

| Family | Label | Its undeletable default | Colour |
|---|---|---|---|
| `bubble` | Bubble text | Regular speech | red |
| `freefloat` | Outside text | Outside text | green |
| `sfx` | Sound effect | Sound effect | purple |

The default sub-type's key **is the family's own name**, which is what every
box already saved on disk says, so nothing has to be rewritten.

**Ten more sub-types per family**, eleven counting the default. Colour stays
inside the family: each family owns a patch of colour space about 24° wide and
its shades are picked to be as far from each other as possible. The three
families sit a third of a colour wheel apart, so nothing can wander into
another's territory, and the yellow of a selected box and the blue of a link
stay clear of all three. A sub-type with no colour, or with a colour from
before families existed, is given its family's first shade rather than drawn in
a colour that lies about which family it is in.

## The nine preloaded sub-types

| Family | Key | Label |
|---|---|---|
| bubble | `narration` | Caption box |
| bubble | `thought` | Thought bubble |
| bubble | `shout` | Burst / shout |
| bubble | `whisper` | Whisper |
| freefloat | `narration_free` | Narration on the art |
| freefloat | `aside` | Aside / mutter |
| freefloat | `sign` | Sign or label |
| sfx | `sfx_big` | Big / impact |
| sfx | `sfx_small` | Small / background |

Narration appears in **two families on purpose**. A caption in a ruled box is a
balloon: a closed shape, cleaned and typeset like one. Narration lying on the
artwork has no shape at all. Same voice, different piece of drawing, and it is
the drawing this list is about.

Yell, Angry and Flashback were removed: a shout, a yell and an angry line are
one kind of typesetting asked for three times.

## What a sub-type controls, and what it does not

**It controls** its label, its colour, and its font. `shout` also raises the
size *ceiling* by 1.15 - the ceiling only, so a burst in a small balloon comes
out exactly as it did before.

**It does not control** any behaviour. The family decides all of that: whether
the box can have a balloon, whether the flat fill may clean it, whether the
typesetter measures against the ink or the box, whether it goes to the
proofreader, whether it may spill out of its box, whether it is clamped.

An unknown sub-type - deleted from settings, or from a newer version's file -
falls back to **bubble**, the family where being wrong costs least, because it
is the one that gets cleaned and typeset normally.

## Seeding

Preloads are offered **once each, by key**. A key you have never been offered is
added; a key you have been offered and then deleted stays deleted. This is why
it is a list of offered keys and not a yes/no flag: a plain flag meant a project
opened before the list existed was stamped as seeded from an empty list and
could never receive anything, and re-adding on every save meant × removed a row
that came back before the panel finished redrawing.

---

# 6. Reading order

A recursive cut of the page, tried in this order:

1. **Panel borders.** A gap with a near-solid ink line running through it is a
   real gutter and is taken before anything else. 92% of the line has to be ink,
   hunted 12px either side. This is what makes a tall panel beside two stacked
   panels read as a column.
2. **Horizontal cuts, searched across every rotation before any vertical cut**:
   0, ±6, ±12, ±18, ±24 degrees. Widest gap first. Rows before columns is how
   these pages read.
3. **Vertical cuts.** Right-to-left takes the right block first; left-to-right
   takes the left.
4. **Fallback.** With no clean cut anywhere, boxes are banded into visual rows
   by their centres (a new row when the drop exceeds 0.6 of the median box
   height) and each row is read across.

A gap under 4px is noise, not a gutter.

The box used for ordering is the **union of the text box and the balloon**.
Tight text boxes invent gaps the balloons close.

Panels are ordered first where they exist, and each box takes its panel's rank;
boxes are then ordered inside each panel with the counter running across the
page.

**Direction** comes from the medium: manga right to left, manhwa and manhua left
to right. The setting overrides it.

## Renumbering by hand

Order is **sticky**. Once every box has a number the page is only compacted to
0..n-1 in the existing sequence: moving or editing a bubble never reshuffles the
page. Geometry only decides for boxes that arrive with no number at all, and
when some are new and some are established, the established keep their exact
sequence and each new box is slotted in before the first established box that
geometry says reads after it.

Drag the number chip in the region list, or hold Alt and type the position.

---

# 7. The seven steps, inside

## 7.1 Find text

**Free, offline, entirely on your machine.** No model call.

The detector is dmMaze's comic-text-detector, an ONNX file run through OpenCV.
The page is letterboxed into 1024px. Two of its outputs are read - the block
boxes and the segmentation mask - and a third, its line detector, is ignored.

A **coverage pass** then re-reads the mask for ink the block head missed, which
is mostly sound effects lying on artwork. There is deliberately **no fill-ratio
floor**: a 0.18 floor was tried and killed 9 real sound effects to remove 8
artwork boxes.

With **Label box types** on, each block is labelled by measurement: a bright
enclosed ring is a bubble; a ring less than 45% bright is outside text; a dark
rule hugging three or more sides is a caption box. **Nothing labels a box by
looking at the drawing.** An AI box-labelling pass existed and was deleted.

With **Text outside bubbles** or **Sound effects** ticked, two more passes run,
in this order and the order matters:

1. **The column reader** runs first, so a body of vertical writing comes back as
   one box rather than a stack of fragments. Ruby joins its body.
2. **The stroke-cluster pass** picks up what the column reader did not.
3. **Fragment absorption** - a box inside a body of writing is a piece of it,
   not a text of its own.

The tick boxes are then applied as a **family filter over whatever came back**,
because the detector ignores them and used to walk straight past them.

After the detectors: blocks read out of one enclosure are grouped as sections of
one balloon and the balloon is divided between them **by nearness**, per pixel,
not by horizontal bands; every sound effect's axis is measured **now**, off the
still-Japanese page, because by typeset time the ink is gone; then the boxes are
scored and ordered.

**Find text replaces the page's boxes.** Boxes it supersedes do not come back.

### What a box carries

Position and shape (the box is of the **text**, not the balloon; the balloon has
its own box and mask); the kind; its panel and its order; a **link** number
(same value = one sentence split across bubbles); a **group** number (same value
= sections of one balloon); the source text and whether it ran vertically; the
sound-effect axis, stored as **fractions of the box's sides** so resizing the
box carries the typesetting; the translation, the speaker and a confidence; the
layout and any hand overrides; a flag; and its cleaning route.

Two more exist only in the editor: **locked** (a line you corrected, which the
reader will not overwrite) and **own text** (a box you added yourself, which is
skipped by the reader, skipped by the proofreader, and not counted).

Boxes are stored as **geometry, not bitmaps** - the masks are rebuilt from the
polygon on load.

## 7.2 Read text

The editor's reader is **always a vision model**. The local readers (manga-ocr
for Japanese, easyocr for Korean and Chinese) exist and are only reachable from
the command-line path.

### How the page is cut

Every tile is kept at or under 1568px on its long edge, which is what the vision
APIs downscale to anyway. **Reading detail** sets the budget: 1 tile, up to 4,
or up to 9. Where the grid would exceed the budget, the axis with the smaller
tile dimension is dropped.

Each box belongs to **exactly one** tile, the one its centre falls in, and that
tile is then **grown** to contain each of its boxes whole plus 16px of air. The
grid divides the work; it is not a hard crop, and a box straddling a grid line
is never sliced.

### What the model is shown

Every inked pixel is settled to exactly one box first, so overlapping boxes are
not read twice. Then, per tile:

* the box being asked about is outlined **red** with a red number;
* neighbours that merely overlap the crop are outlined **grey and unnumbered**;
* **the words are painted back in front of the lines**, because a box border is
  an annotation and nothing gets to cover the glyph being asked about;
* the numbers are drawn last, at whichever corner of the shape covers the least
  ink.

The outline follows the **shape** of the words rather than being a rectangle,
grown 4px per side - the line is 2px thick and drawn on the page the reader
sees, and a border along the edge of 見 made it come back 悪魔.

### What it is told

Red means transcribe, grey means ignore completely. Read only what the outline
encloses; where a line falls inside two outlines it belongs to the one that fits
it most closely. Copy the source characters exactly, in reading order. Original
script only: **do not translate, do not romanize**. **Do not include furigana** -
transcribe the main line only. Transcribe only what is printed and never guess:
an unreadable or empty box returns nothing, and *"a plausible-sounding line that
is not clearly in the image is WRONG"*. Small kana and dakuten are preserved.

Every request also carries the **whole page's** box list so a tile is never read
blind, up to 60 glossary terms as printed-to-rendering pairs, up to 40 character
names, and the **link groups**, with an explicit instruction that a name broken
across a split must not be repeated or completed in either half.

Names may be used **only to settle an uncertain glyph**, never inserted into a
box that does not visibly contain them.

### What comes back

One reply per tile. Anything it volunteers about a box that was not asked for is
dropped - that was read off a greyed neighbour. **The first answer for a box
wins**, not the last.

A box that is **locked** and already has text is never overwritten. An empty
answer flags the box "no text read". A garbage check then catches an empty
result, punctuation only, seven or more identical characters in a row, or a
length implausible against the amount of ink - measured on visible characters
only and deliberately loose, to catch a true runaway and never second-guess a
dense small-font bubble.

## 7.3 Translate

### What is sent

A JSON payload, in a **deliberate key order**, because the order is the cache.
The fixed part first:

1. the medium
2. the source language
3. the target language
4. whether to keep honorifics
5. `do_not_return`, only when a story switch is off - the fields the reply must
   leave out entirely
6. the synopsis
7. the glossary
8. the chapter context, when there is one

With **Keep a story** off, keys 6 and 7 and the character sheet are not sent at
all, and the prompt reads a missing field as *"one nobody is keeping for this
project"*.

Then the moving part: the character sheet, the last six lines of the previous
page with their speakers, and the boxes.

Each box sends its id, its panel, its kind, its text, the source character
count, and its link number when it has one.

`chapter_context` sits **up with the fixed things** because it is fixed for the
*run*, which is what a cache is measured over. It used to be appended after the
boxes, which put about 4,500 tokens just past the end of the cacheable prefix.

### The chapter context

**Every other page**, not a window: the finished translation where one exists
and the source text otherwise, skipping the pages in this run because their text
is about to be replaced.

A **full-chapter run sends none at all** - every page is in the run, so there is
nothing to be consistent with. The price is counted off the same function, so
the quote and the payload cannot drift apart.

### Prompt caching

Anthropic is asked explicitly: the fixed half of the payload and the system
prompt are marked as cacheable blocks, but only above 4,096 characters, because
below that a cache write costs more than a plain read. The reader's system
prompt is left unmarked; the translator's is marked.

Google's cache is implicit and free and asks only that the repeated bytes come
first, which is what the key order buys.

The model reads the string joined back together. Only the billing sees the seam.

### What the prompt says

The interesting parts, in the prompt's own terms:

* **The synopsis is ground truth** and must never be contradicted.
* **Use exactly the character sheet's pronouns and voice, on every line.**
* Propose a new character **only** if they are named, recurring, and the name is
  printed on the page or already in the synopsis or the sheet. Never a one-off,
  never the narrator, never "Crowd" or "Guard A", and never a coined label like
  "the blonde girl".
* The glossary is for proper nouns that are **not people**. **Every rendering
  must say what the thing is, in brackets.** A bare name is refused. A term you
  were given without a bracket should be re-proposed with one - that is the only
  way an empty entry ever gets filled.
* A speech bubble is a person **talking**, never a headline or a colon-list.
  Narration may be clipped; dialogue may not.
* **Speaker attribution first**, because most pronoun mistakes are speaker
  mistakes. Never invent a name; a plain role label is always correct.
* **Never introduce a dash the original does not have.** A carried sentence ends
  with three periods. Never start a line with an ellipsis the source does not
  start with.
* Sound effects render as bare comic effects, never wrapped in asterisks.
* **Never censor.** Masking with symbols or softening a swear is a
  mistranslation. The only exception is mirroring a mask the page itself carries.
* A wordless sound in an ordinary bubble is onomatopoeia: render the **English
  sound**, not a transliteration. すー… is "Hahh…", not "Sooo…".

### Getting it back

Three attempts. Broken JSON is repaired (unescaped quotes, literal newlines,
smart quotes used as delimiters, trailing commas) before it is parsed. A
truncated reply is asked to answer tersely; bad JSON gets the escaping rule.

**The set of ids that comes back must equal the set that went out, exactly.** A
missing one is listed by number and the reply is rejected, because a missing box
is a blank bubble in the finished page.

### After the model

In order: typographic characters comic fonts cannot draw are normalised; a
leading or trailing dash is stripped **unless the source has one** (a single ー
is an ordinary long-vowel mark and does not count; dashes inside a line are left
alone); a leading ellipsis is stripped unless the source opens with one, reading
past opening brackets and quotes on both sides.

Then the censor check flags a word the model masked that the page does not mask -
carefully enough that "5 * 4" and "WOW!!" do not trip it. A confidence below 0.5
adds a flag.

### What may reach the sheets

**All of this is behind the story switches.** The glossary merge needs **Keep a
story** and **Add places, terms**; the character merge needs **Keep a story**
and **Add characters**. With either off the proposal is dropped whatever it
says.

**The glossary.** A rendering with no bracketed note is refused. A described
entry fills in an existing bare one, keeping the sheet's spelling. A described
entry **never re-words** one that is already described: first sighting is canon.
The name and note are split on an opening bracket, or on a dash **with spaces
around it**, so "Half-Moon Gate" is a name and not "Half" described as "Moon
Gate".

**The character sheet.** Three refusals: a second spelling of somebody already on
the sheet (first sighting stays canon and the variant is not added beside it); a
generic bit part; and a name **written nowhere in the story**. Evidence is
pooled from the sheet, the synopsis, the glossary, the previous page's tail, and
this page's own source **and** translated text - built after the translations
land, because a character is usually named by somebody addressing them on this
very page.

Romanisation is folded before comparing: l and r, v and b, ou/oh/oo/ow to o,
uu/uh to u, ei/ee to e, doubled letters collapsed. Glow, Glou, Grow and Grou are
one man.

**The same rules apply to a hand-pasted reply.** A reply you paste in cannot put
anything on the sheets that the live translator could not.

### Speakers

With **Name who is speaking** off, the speaker is discarded on arrival and
neither pass runs. With **Keep a story** off, both passes are skipped: there is
no sheet to snap to and nothing to be evidenced against.

Otherwise, two passes, in this order and not the other:

1. Every non-generic speaker is matched against the sheet and **snapped to the
   sheet's spelling**. This has to run first: the sheet is part of the evidence,
   so a loose spelling of a known name looks well-evidenced and would never
   reach step 2.
2. Whatever is left and is written nowhere is flagged *"speaker X is not named
   anywhere"*. The label is **kept** - it may still be the right person - but
   marked, so it is not mistaken for something the page established.

Two names are the same person if their folded forms match, or differ by one
edit on forms of five characters or more whose lengths differ by at most one.
Leonora and Leonore, yes. Mimi and Momi, no.

## 7.4 Proofread

Runs on the stored records rather than the pictures, so flags survive. It does
nothing if nothing is translated.

Before anything is sent, stored speaker labels are **snapped to the settings
sheet's spelling**, so the pronoun check reads the same name the sheet is keyed
by. The previous page's last six translated lines go with it, each tagged with
its speaker.

**Excluded from the request:** sound effects (CRASH needs no copy edit, and a
model asked to polish one turns it into a sentence) and any box you typed
yourself (there is no source to check it against).

### What it checks

Never censor or un-swear. Lines that are not natural in the target language, or
do not make sense against the source. A bubble reading as a headline or a
colon-list gets rewritten as speech; narration may stay clipped. **The page read
as a conversation** - each line must follow from the one before, and the first
from the previous page's tail; an answer that does not answer the question is a
mistranslation even when it is a fine sentence. Linked boxes are proofread as
one sentence and handed back **still split in the same place**. Pronouns against
the sheet, including in the speaker's own lines; where the referent is unclear it
must **leave the line alone and say so**. Names snapped to the sheet's spelling.
No proper name the sheet and glossary do not contain. Grammar, tense, agreement,
spelling, punctuation. Consistency across the page: where two lines disagree the
sheet decides, and where the sheet says nothing **the first use on the page
decides**.

### What it may change

*"A line that is already right comes back UNCHANGED, character for character. Do
not rephrase for taste; this is a proofread, not a rewrite."* Nothing invented.
**Never meaningfully longer** - it has to fit the same bubble. Plain
punctuation, no added dash, and a leading ellipsis the source does not have is
removed.

### The notes

`page_notes` is for **what it could not fix**, one short sentence each, and
every remark must start with **"Box 5:"** or **"Boxes 5, 7:"** using the box
number, because a remark with no box named is unusable.

### The spelling enforcement

The half a prompt cannot promise, because every page looks consistent with
itself. A table of canonical form to canon spelling is built from the glossary
renderings and the character names, **the sheet winning collisions** because it
is what a human edits. Then every capitalised word of three characters or more
that is not a common capital or a title word:

* if its canonical form **is** a canon term, it is rewritten silently, keeping
  the case (a SHOUTED line stays shouted) and reported;
* if it is merely **near** one - one edit, both at least three characters, at
  least one of four - it is **left exactly as written** and reported on the box,
  because a proofreader that quietly merges two characters is worse than one
  that asks.

Words this chapter uses in lower case anywhere are treated as ordinary words:
"watch it grow" means Grow is a verb here.

### What it writes back

A changed line replaces the text, **clears the layout** and drops the fitting
half of any override, because stale typesetting must not outrank new wording.
The page note is set unconditionally, so a clean re-run clears the last one, and
the list of changed boxes is the **factual** one - worked out from what actually
changed rather than taken from the model's prose, which talks in numbers you
never see.

### The report

Markdown, three sections:

1. **Still wants a look** - every flag from any stage, with the page, the line,
   the box number, the speaker, the reason and the English underneath.
2. **Across the whole chapter** - the audit below.
3. **Script** - every page in order, with the page note as a blockquote and then
   each line numbered, with its kind, speaker, box number, Japanese and English,
   and any flags. Both numbers are printed because the notes talk in box ids
   while the script counts lines down the page.

### The chapter audit

The point of the report. Every other check in the program runs on one page, and
a page cannot notice it spells a name differently from page 30.

* **One name, two spellings.** Every capitalised word is folded and any
  canonical form with more than one surface form is listed with counts and page
  and line references. It does not guess which is right.
* **A Japanese honorific welded to a name** - `Name-san`, `-sama`, `-chan`,
  `-kun`, `-senpai`, `-sensei`, `-dono`. Raised **only when the chapter has
  clearly decided against keeping them**, so a chapter that keeps honorifics
  throughout is not nagged about its own house style.
* **Speakers the character sheet does not have** - their lines got no pronoun
  check.
* **Text read but never translated**, per page.

## 7.5 Clean

Pressing **Clean** means *clean these pages*, so it throws the cached plate away
first. Everything else that needs a plate - opening a page, typesetting,
exporting - reuses.

### The four routes

Chosen per box:

| Route | When | How |
|---|---|---|
| **Flat fill** | The background round the box is flat, and the AI is not doing the whole page | The exact background colour painted over the mask, grown by a measured halo. Instant, exact, and no model beats it |
| **Pattern copy** | No model configured, and the background is screentone | Real dots slid in from nearby, run **first**, on the still-untouched plate, so the sources are clean neighbours. Flagged as worth a look. A stand-in for a model, not a preference |
| **Telea** | No model configured, not flat, not screentone | One classical inpaint over everything left |
| **The hosted cleaner** | A model is configured | One call **per box**, on a crop with 96px of page around it |

**Why per box and not per page.** A hosted inpainter handed a whole page splits
the mask into connected pieces itself and runs once per **glyph**, each seeing a
window too small to tell what the background was doing.

### Flat versus the model

Once a model is configured, the local path keeps only what it is unbeatable at:
a background that is not merely flat but **white** - very low spread, very high
level. And **never for outside text or sound effects**, whatever the numbers
say. A column of outside text on a white cloak passes every flatness test: the
cloak is white, it is flat, and the sample never reaches the hatched hood eight
pixels away. A cloak is not a bubble.

The test is the **family**, not "is it on artwork", because "on artwork" also
says yes when no balloon was *found*, and a balloon the finder missed is still a
balloon.

### Building the mask

Skipped entirely for a box with no mask or with **keep original** on.

Light text on a dark panel is detected and the mask is rebuilt from a
letter-like split - **except for sound effects**, where the box's own ink is its
area, so the vote would be taken over the strokes themselves.

The mask is clipped to the **text box** plus 3px. The cleaner should only clean
the box that has the text: the balloon mask is right for measuring the
background and wrong for erasing. Marks that are mostly outside are dropped, and
each caught stroke's whole connected component is completed, as long as most of
it is inside the box and it never reaches more than 8px past it.

**If every filter empties the mask**, it falls back to the detector's own mask
clipped to the box, and flags the box. None of those filters is a reason to
erase *nothing*.

Model masks are **more generous** than local ones - the model reconstructs
whatever it is handed, so a stroke edge left outside the mask is a stroke edge
left on the page, and being generous costs nothing.

**Core-only fallback.** On the inverted path, if the widened mask covers more
than 55% of the box, it drops back to the letter-like core with no halo and no
padding and flags the box. It used to give up and leave the box untouched, which
is how a page came back with its sound effects and narration still on it.

### The fence

After everything - halo, model padding, ghost sweep, page-wide screentone copy -
every pixel outside a box's own area plus 8px is put back from the original. One
fence, at the end, so no step added later can forget it, and the same rule for
the local fill and for the model.

### Keeping a bubble

The expensive inpainting runs **once, with every bubble cleaned**, and is cached.
The per-bubble eye then only pastes original pixels back. Restoring one bubble
pastes back that box's **mask** grown by 16px, **not its rectangle** - boxes
touch and overlap, and a rectangle brought the neighbour's Japanese back - and
never over a pixel another box is having cleaned.

### Your own cleaned page

Point a page at a file you cleaned yourself and it is used as the plate outright,
resized if the dimensions differ. **Nothing is inpainted, nothing is sent to the
hosted cleaner, nothing is pasted back, and the per-bubble eyes do not apply.**
The page is marked cleaned, or the Clean step would sit at 22/23 for ever and
Typeset would never look finished. One page at a time.

### The caches

| Cache | What | Size |
|---|---|---|
| Plates, in memory | The cleaned page | 6 |
| Plates, on disk | The same, under `plate_cache/` | 80, or three per page |
| Hosted cleaner replies | Per box, keyed on the image and mask bytes | Unbounded |
| Rendered pages | The JPEGs the browser sees | 96 |

The plate key includes the **contents** of the source file, not its name and
size, because chapters are numbered identically and page 1 of a new chapter had
the same name and size as the old one. It also includes a version stamp for the
cleaning **code**, precisely because none of the other keys change when the code
improves, and every improvement used to ship invisible.

The hosted-cleaner cache is deliberately **not** cleared by pressing Clean: a hit
is the same picture the endpoint would send back, for free.

A plate built while the cleaner was refusing is **not cached** - otherwise
"press Clean again" found the smeared plate and never retried.

### What it costs

**A flat fee per page, and only when the hosted cleaner actually did some of it.**
A cache hit, a page using your own plate, and a whole chapter filled flat on your
own CPU all cost nothing.

### What it reports

Every box records the route it took, and the page counts them: filled flat, by
the AI, locally, tone copied, core only, fell back, kept, skipped. A count for
the chapter says six were filled flat and cannot say **which**, so both exist.

## 7.6 Typeset

Pressing **Typeset** means "lay this page out again", and it means it: every
hand override is cleared and **every text box you drew yourself is removed**.

The courtesy re-typeset that follows new words arriving - a translation file, a
pasted reply - is different: nobody pressed the button, so your own boxes are
taken out, the page is laid out, and then they are **put back**.

### What is measured against

The balloon where there is one. For a sound effect, **the ink**. For everything
else, **the box** - not the ink. Japanese runs in tall narrow columns with holes
punched through it, and measuring English against that shape is why speech with
no balloon came out at single figures in a box with room for twenty.

### Line breaking

An exact search over every way of splitting the words, minimising raggedness,
with a small bonus for breaking after punctuation and a small penalty for
breaking before a short function word.

**Every line counts equally.** The classical algorithm leaves the last line free,
which is right for justified prose and cheap to compute; comic typesetting wants
a balanced block.

### The size sweep

The largest size that yields any layout is found first, and the ladder is walked
down from there over three line spacings. The walk stops early on a proof: every
term in the score is non-negative and the "too small" term depends only on size,
so once that floor exceeds the best score in hand, the rest of the walk is
arithmetic whose answer is known. On one specimen this typeset 3 sizes instead
of 25.

Everything is measured against the balloon **eroded** by a margin, so a line is
judged on how close its ink comes to the outline in **any** direction, not only
sideways. Block height uses ink extents rather than line boxes, because the top
line's ascender gap and the bottom line's descender gap are empty.

The block is tried at eight heights within the slack, and then **slid back to the
most central height its now-fixed lines still fit**. The height search exists to
find room, not to decide where the words end up.

All lines sit on **one axis**, not each centred on its own chord.

### The score

Seven terms: line count, raggedness, imbalance, orphans, vertical fill,
smallness, and characters per line. Three of them are worth explaining:

* **Vertical fill is a one-sided ramp** priced very high. It is a floor, not a
  preference, and it contributes nothing at all to a well-filled block.
* **Smallness is measured against the largest size this balloon can actually
  take**, not against the number in Settings.
* **Orphans only count when some other line holds more than one word.**
  "HELLO, / EVERYONE!" has no arrangement that is not one word per line.

Line count is penalised past a soft limit that **the balloon's own shape gets a
say in**: in a tall narrow bubble, many short lines is the shape doing what it
was drawn to do.

### What is never done

* **No hyphenation, ever.** It was tried and hated.
* **A word is never split.**
* **A sentence is never cut.** The full translation goes in, always. Line breaks
  and size do the fitting.
* Automatic answers never go tighter than 1.20 line spacing. A number you type
  is a person deciding and stands however tight.

**Breaking at the author's own dashes is a different thing** and is allowed, once
nothing else works: at a dash, keeping the piece before it (GLOW- / SAN!), and at
a run of dots, keeping the piece after (CLOSELY / ...). Any pair the fitter did
not actually break is rejoined with no space.

### The cascade

In order, stopping at the first that works:

1. **A sound effect** goes straight to its own fitter.
2. The ordinary fit.
3. **Two lobes** - a balloon with a waist typesets as two lobes if that
   typesets bigger.
4. The same search, allowed to break at the author's dashes.
5. **Spilling, for outside text only** - and **before** the narrower fit, which
   is the whole point. The box round free text is where the *Japanese* was, a
   narrow column, so a narrower fit will always find a way to stack one word per
   line, and that is a tower, not typesetting. It sets at the minimum size,
   never below, wrapped to the box's width where it can and past it where it
   cannot, centred so the overflow is shared.
6. **Narrower, for speech** - the same search with the line limit lifted to 24.
   More lines is a narrower line. A balloon is a wall.
7. A plain rectangular wrap, sweeping down to an absolute floor of 7pt. Flagged
   "shrunk below the minimum font size" **only if it actually went under** your
   minimum.
8. One clamped line at the floor, flagged "text cannot fit this box at any
   legible size".

### Glyph substitution

With it **off**, the words are set in the face you picked and in no other. A
character the font cannot draw is left in and the box is flagged by name.

With it **on**, a block the chosen face cannot draw falls through to a spare
face and is flagged with the substitute's name. If nothing can draw a word of
it, the page **keeps whatever was on it** rather than replacing readable
typesetting with nothing.

### Fonts per box type

An override on the block wins, then the sub-type's own font, then the family's,
then the project's. A sub-type's font is folded in on the server, because a
setting that only works while the page that wrote it is open is not a setting.

### Spilling and staying on the page

A block marked as spilling is not clamped back into its box, and is not clipped
to the balloon at drawing time - cutting it back at the last moment would lose
the first and last letters of every line.

**Out of the box is allowed. Off the page is not.** Every layout is slid back
onto the page, accounting for rotation. A block wider than the page is left
alone, because there is nowhere to put it.

### Sound effects

The axis was measured at Find text, off the Japanese, and stored as fractions of
the box. Below 4 degrees nothing is rotated - scan noise moves it a degree or two
and a rotated paste costs sharpness. Above 40 degrees it is not followed. A shape
rounder than 1.5 to 1 has no meaningful long axis and the box's shape is used
instead. A gap along the axis longer than the effect is wide means the box holds
two things and the angle is refused.

The English is set as **one line however the Japanese ran** - a column of English
capitals reads as a ransom note. It may run to 1.02 of the original's length and
1.35 of its width, and it sweeps from 160pt down to **your minimum**, not to the
absolute floor: an effect is drawn on artwork, and running past the box beats
being too small to read.

### Locked and edited

A block you corrected is marked locked, and from then on it is rebuilt from your
override rather than re-fitted: never overridden, never clamped, never
re-anchored, and its flag is cleared.

A re-fit clears exactly the **fitting** keys - lines, size, spacing, offsets,
frame, rotation - and keeps how the block was **dressed**: face, colours,
outline, shadow, letter spacing. Dressing is a choice about the page, not a
correction to the fit.

Two details worth knowing: a block whose lines are all blank is kept as an empty
box **at the size it was left at**, so you can click into it and type again
rather than watch it snap back to the fitter's answer; and a block nobody has
moved is placed by the same arithmetic the fitter uses, because centring it in
its bounding rectangle instead is what made typesetting jump the moment it was
clicked.

### Colour

After the layout, each block is given its text, edge and stroke colours, so the
browser's preview matches the export. Light-on-dark is decided by reading the
**original scan**, splitting it, and naming the ink as whichever class the text
box has a bigger share of than the balloon around it - which survives a hatched
balloon carrying white type, where any brightness average fails.

## 7.7 Export

Three modes:

| Mode | What it writes |
|---|---|
| **Finished pages** | Cleaned art with the English typeset on. Typesets **without** clearing hand work, so exporting never quietly discards it |
| **Cleaned pages only** | The plate: the Japanese erased, no English. The same plate the typesetting would have been drawn on, so it costs nothing extra |
| **Boxes drawn on** | The original art with the boxes, the reading-order numbers, the type colours, the faint balloons, the link colouring and a frame round each balloon group. **No cleaning, no typesetting** - it reads the stored records and copies the picture, which is why it is instant |

The dialog also has **Which pages** (every page, or only this one), **Save into**
with a **Browse…** where the machine has a dialog, and **Folder name to create
there**, with the finished path shown live.

**Only Finished pages ticks the Export step.** The other two append `-cleaned`
or `-boxes` to the folder name so they cannot overwrite it.

Each page is written as `<page name>.png`.

Being exported is recorded **on the project**, not inferred from what is in the
folder, because the folder outlives the chapter and a new project pointed at it
would otherwise "have results" made by the last one.

**The zip** takes only the PNGs and JPEGs from the export folder, flat.

**The translations JSON** is every page and every box: id, order, kind, Japanese,
English, speaker. Hidden boxes are excluded.

---

# 8. Webtoon strips

A webtoon uploaded as tiles is re-joined and re-cut into pages, automatically,
when a chapter finishes loading.

**It only triggers if all of these hold:**

* the setting is on;
* **no page has any work on it** - having a chapter you had found boxes on,
  cleaned and typeset rearranged underneath you is worse than the problem;
* it is **sure** the images are a sliced strip. All four tests must pass: more
  than five images; every one the same width (a scan of paper pages never is);
  all but the last the same height **to the pixel**, which is the signature of a
  machine slicing by count, the last exempt as the remainder; and at least 1.2
  times taller than it is wide.

**The measurement this exists for.** Chapter 1 was 690 × 167,617 pixels, cut
into 105 tiles of exactly 1600px. Of the 104 cuts, **86 land on ink, 63 go
through a speech balloon, and 38 through the typesetting itself** - one straight
across 지구인 용사 소환!, leaving half the glyph heights on one file and half on
the next.

**How it cuts.** A row profile is built tile by tile; nothing ever loads the
whole strip, which at that size is 347MB. A row is empty when it has both low
variation and a small range - both tests matter, because variation catches
texture and typesetting while the range catches a hard edge in an otherwise even
row, like a panel border crossing a margin. A **band** of six or more empty rows
is a gutter; a single flat row is a coincidence.

Cuts are taken at the gutter **nearest** the target height, not the first one
past it: first-past overshoots where gutters are sparse, and a chapter of
3,500px pages when you asked for 2,400 is not what was asked for.

**When there is no gutter**, it runs on to the next one after the window if it is
still under the ceiling. Failing that it cuts at the **quietest row** - the middle
of the longest run of empty rows in the window, even if that run is too short to
be a gutter, because a two-pixel gap between panels is not a gutter and is a far
better place to cut than the middle of a face. Every forced cut is recorded and
**the page is reported by name** so you can look at it.

The ceiling exists for a concrete reason: the detector letterboxes a whole page
into one 1024px square, so on a 10,000px page the typesetting arrives about 70px
tall and it starts missing text.

**Your tiles are kept, never deleted.** In our own upload folder the new pages
replace the tiles where they stand and the tiles move into `input/tiles/` - the
lister only looks at the top level, so they stop counting as pages while staying
exactly where they were put. In somebody else's folder nothing is touched at all
and the pages are written elsewhere.

**Rollback:** if fewer than two pages come back, the tiles are moved back, the
written pages are removed, and the project is left exactly as it was found.

Result on that chapter: 81 gutters, 43 pages, zero cuts through anything.

---

# 9. Accounts and coins

## 9.1 What a coin is

**A hundred coins is a dollar.** Every price in the code is written as a real
provider cost in dollars and passed through one function, which multiplies by
two and rounds **up**.

The doubling is in exactly one place, so no step can forget it. Set it to one
and the app charges cost price; nothing else changes.

**Up, never down, never to nearest.** Rounding down is a free tier for anybody
who can arrange to land just under. But it is the ceiling of the **real**
number, not a floor of one, so something that cost **nothing** - a model on your
own machine, a page with no text - still costs nothing, while anything that cost
a fraction of a cent costs one coin.

**The rounding happens once per run**, not per page and not per API call. A page
of translation costs well under a coin, so rounding per page would flatten the
per-box pricing into a flat rate.

**One thing rounds down**, and it is the clawback when a purchase is refunded:
a partial refund never takes back more of the coins than it did of the money.
Both directions favour the customer.

**An unpriced model is charged at the dearest rate on the list**, and the app
says so on screen. A model charged as free is a bill this app eats; one charged
as expensive that was cheap is a customer who can be refunded. Only one of those
is recoverable.

**No dollar figure is ever shown in the editor.** Coins only.

## 9.2 What costs coins

| Step | Charged | How |
|---|---|---|
| Find text | No | Runs on your machine |
| **Read text** | Yes | Per text box on the page |
| **Translate** | Yes | Per box on the page, **plus** per box of chapter context sent with every page |
| **Proofread** | Yes | Per box on the page |
| **Clean** | Yes | **A flat fee per page**, and only when the hosted cleaner did some of it |
| Typeset | No | Runs on your machine |
| Export | No | Runs on your machine |
| Any step on a local model | No | |
| A page with no text boxes | No | |

Cleaning is flat per page because a hosted GPU costs what it costs; the number
of bubbles does not change it.

## 9.3 How a price is worked out

Each of the three text steps has a measured **token shape**: a fixed cost for
the request, a cost per box on the page, a cost per box of context, and an
output cost per box. Translation also carries a large **per-page** thinking cost
on models that think - per page, not per box, because a two-box page and a
ten-box page do not reason a fifth as hard. Getting that wrong is a five-times
under-quote on Gemini or a seven-times over-quote on Claude.

The shapes were fitted against the real prompt builders at 2, 9 and 20 boxes a
page, and checked against a real invoice: one 23-page chapter on Gemini 3.6
Flash cost $0.508, of which about 39,000 of the 44,870 output tokens were
thinking rather than reply.

**Prompt caching** is priced only where it is real and askable. Anthropic is
asked explicitly and the saving is priced. Google's implicit cache is real and
cannot be requested, so pricing it would undercharge; it is left out. The
reader's system prompt is under the caching threshold and is paid in full every
page.

### The drift correction

The shapes were fitted to one chapter of one series on one model. A gag manga
with three words a bubble and a dense fantasy webtoon do not cost the same per
box, and no constant will ever know which is on screen.

So every run writes down what it **really** used beside what it was quoted, and
the next quote is corrected by the ratio.

* It looks back over the last **8** runs of that step on that model.
* A run of fewer than **20 boxes** is noise and gets no vote. It is still
  measured, it just does not vote.
* Nothing may more than **double or halve** the shape. One provider having a bad
  day, one chapter of nothing but sound effects, and an unclamped correction
  would carry that into every quote afterwards.
* It is a **sum over runs, not an average of ratios**, so a 40-page run outweighs
  a one-page run.
* On a fresh install both corrections are exactly 1.0 and nothing happens.

The corrections are **frozen for the length of a run**, so a cancelled run's
charge and its refund are priced against the same evidence.

## 9.4 The purse

The popover shows, in order: the balance; who you are signed in as, or an offer
to sign in; **This chapter, all N pages** with one row per paid step and an
**Everything** total; a note explaining per-box pricing; a warning naming any
model that is not priced; and **Buy coins**.

**Every price is worked out on the server**, for the whole run and for the single
page, and never assembled in the browser out of per-page numbers - 23 pages
rounded up individually is 23 coins whatever is on them.

While a run is spending, the count draws balance minus spent. That number is
drawn, never stored, or the count would fall twice as fast as the money.

### When you cannot afford it

Asked **before** anything starts, on every paid step:

> not enough TCT Coins - this needs `N` and there are `M`. Run fewer pages, or
> buy more coins.

The balance is re-asked of the server at that moment. There is no such thing as
a run that pays for what it can and stops: the whole price is taken up front.

### The refund

At the end of a run, the pages it never reached are priced with **the same
context total the charge used** and given back. A run that finishes gives back
nothing. A run you cancel gives back the rest.

The refund is rounded up too, which can make it a coin more than those pages'
share of the price. Rounding a refund the other way is rounding in the seller's
favour, and this is the seller's own app.

## 9.5 The meter

Every paid run writes a line recording what it really cost, **even when you are
signed in**: the account's ledger records what was *charged*; what a run really
cost is a question about this machine's calls.

Each line carries the step, the model, the backend, the coins it really came to,
the real input, output and cached tokens, the number of calls, what was actually
kept after any refund, the boxes and pages it finished, and how much context it
sent. Those last few are what turn a receipt into evidence - they are what the
drift correction reads.

`python -m mangatl.coins accuracy` prints runs, boxes, charged, really, and the
two corrections per step and model.

## 9.6 The local purse

When you are not signed in, coins live in `wallet.json` under `~/.mangatl`,
written atomically. A new one opens with **1,000 coins**. The ledger keeps the
last 400 entries.

A local spend **is allowed to go below zero**, deliberately: it is recorded
*after* the tokens were bought, and refusing the entry would not un-spend the
money, only lose the record. The check before the run is what keeps the balance
positive.

`python -m mangatl.coins add N` exists so the author cannot lock himself out,
and is deliberately a command rather than a button.

## 9.7 Accounts

The editor never writes a balance. It only asks.

| Action | How |
|---|---|
| Sign in, sign up, reset password | Firebase Identity Toolkit directly |
| Claim a username | A Cloud Function |
| Ask who I am and what I have | A Cloud Function |
| Spend, refund | Cloud Functions |
| Set the profile picture | A **direct Firestore write** - the rules already allow exactly that field, and a function would only be a slower way to hit the same rule |
| Sign out | **Local only.** Nothing is revoked. Signing out of this machine is not signing out of the account |

Tokens live in `account.json` under `~/.mangatl`, created with owner-only
permissions **before** anything is written to it, because a refresh token is a
credential.

### Username rules

Enforced on the server, in one file.

* 3 to 20 characters.
* Letters, numbers, dot, dash and underscore only.
* Must start and end with a letter or a number.
* No two punctuation marks in a row.

**Then it is folded**, and uniqueness is checked on the folded form: lower-cased,
normalised, with dots, dashes and underscores removed, and a set of confusable
digits and letters mapped together - 0 to o, 3 to e, 4 to a, 5 to s, 7 to t, and
the whole 1 / l / i family.

So `Lee`, `lee` and `LEE` are one claim; `lee.m`, `lee_m`, `lee-m` and `leem` are
one person; and `adm1n`, `admln` and `admin` are one name. `rn` versus `m` is
explicitly not attempted - it cannot be done without banning half the dictionary.

After folding the name must still be three characters, and it must not fold onto
one of **38 reserved names**: admin, administrator, root, system, support, help,
staff, mod, moderator, official, mangatct, tct, team, billing, payment,
payments, account, accounts, settings, login, signin, signup, register, logout,
api, www, app, about, pricing, terms, privacy, contact, null, undefined, me,
you, anonymous, deleted.

**The display form is what you typed.** The folded key is only what uniqueness is
checked against.

### The profile picture

Ten presets, drawn rather than uploaded: fox, cat, moon, star, bolt, leaf, wave,
ink, panel, brush. An upload means a storage bucket, a size limit, a content
check and a moderation problem.

## 9.8 The server

Seven functions:

| Name | Does |
|---|---|
| `claimUsername` | Validates, then in **one transaction** deletes the old name and creates the new one. Released-first loses the name if it fails; claimed-first leaks two names on a crash |
| `usernameFree` | Says whether one name is free. Deliberately says nothing about **who** holds it |
| `spendCoins` | Takes coins against a run id. A retry with the same id returns what it charged the first time and charges nothing |
| `refundCoins` | Gives back, capped at what that run actually took |
| `me` | Balance, username, picture, and the pack list. Usually where an account's document comes into existence |
| `checkout` | Makes a Stripe Checkout Session |
| `stripeWebhook` | Verifies the signature **first**, then handles the event |

**All amount logic is in a separate, Firebase-free file.** The rule is: if an
`if` in the function file decides an amount, it is in the wrong file.

An account starts at **zero on the server**. There is no welcome grant, because
a free sample anybody can have again with another email address is not a free
sample, it is the price.

### The security rules

* Your own user document: you may read it. You may **not** create it, delete it,
  or change anything except your display name and your picture, with length
  limits on both. Coins, username, the Stripe customer id and the grant records
  are unwritable by any client.
* Your ledger: read only.
* Usernames: anyone may ask about **one** name, nobody may list them all, nobody
  may write.
* Prices: anyone may read the public list, nobody may list the collection,
  nobody may write.
* Everything else: denied.

The file ends with a catch-all denial, because a rules file that ends without one
is one forgotten rule away from being open. It is strict precisely because the
functions bypass it entirely.

### Grant once

Four separate mechanisms, all keyed on an id somebody else generated:

* **Spends** on a run id you generate before the coins are taken.
* **Refunds** capped by what that run recorded.
* **Purchases** on the Stripe session id, so a webhook delivered twice credits
  once. Stripe *will* deliver twice eventually.
* **Clawbacks** on the charge id **plus the amount**, so a second, larger refund
  on the same charge is a different key and is processed, while the amount
  already taken back is remembered so it is not taken twice.

## 9.9 The packs

| Pack | Coins | Price | Coins to the dollar |
|---|---|---|---|
| pack1 | 500 | $4.99 | 100 |
| pack2 | 1,050 | $9.99 | 105 |
| pack3 | 2,150 | $19.99 | 108 |
| pack4 | 5,400 | $49.99 | 108 |

One-off, no subscription. Coins never expire, there is one balance, no cap, no
second pocket and no allowance. Three earlier designs were tried and discarded,
including a three-month cap whose counter double-counted and a two-pocket scheme
that needed an expiry to explain on the pricing page.

Every price **includes tax**: Stripe is the merchant of record and takes each
country's sales tax, VAT or GST out of the figure rather than adding it on top.

### Buying, end to end

1. The pricing page draws the packs - from your account when signed in, and from
   the public price list otherwise, because a price list that needs an account is
   a price list nobody reads.
2. **Buy** while signed out goes to sign in and comes back and presses the same
   button.
3. The function resolves the pack, makes or reuses a Stripe customer, and returns
   a Checkout Session URL carrying your account id.
4. You pay on Stripe.
5. You come back to the account page, which **watches** your balance rather than
   reading it once, so the number changes when the webhook lands. "I paid and
   nothing happened" is the worst minute in the product.
6. The webhook credits the coins.

### Refunds

Exactly two webhook events are handled. Everything else is answered 200 and
ignored.

* **A completed checkout** credits the pack, once, keyed on the session id.
* **A refunded charge** takes the coins back.

The pack is asked of Stripe rather than remembered, so it works for charges made
before this code existed; if that lookup fails the function **throws**, so Stripe
retries, rather than letting the coins stay.

**A full refund takes the whole pack's coins**, not a proportion - under Managed
Payments the tax is withheld and returned, so the money back can genuinely exceed
the money in, and a proportional formula would claw back more than the purchase
ever granted.

**A clawback is allowed to take the balance negative**, deliberately. Somebody
who bought 3,000 coins, spent 500 and then took all their money back sits at
**minus 500**, not zero - otherwise the 500 coins of work were free and the trick
works again tomorrow. Nothing collects that debt; spending simply refuses until
the balance is positive again.

Fractions are refused everywhere. Truncating one looks harmless and is how 0.5
becomes free: a caller that can send fractions can send a million of them.

---

# 10. Files

## 10.1 The two file types

**`.tctp` - one chapter, everything.** A zip written by the server holding the
manifest, the project (every box, both languages, every layout, the settings
including your API keys, the story bible, the custom box types), the pages, the
original webtoon tiles where there were any, your paint layers, any cleaned
plates you supplied, and **every font the chapter typesets in** - fonts live
outside the project folder and would otherwise be the one thing that did not
travel. Paths are stored relative and made absolute again on opening.

Left out on purpose: the plate cache and the hosted-cleaner cache. Both are
rebuildable and usually bigger than the chapter.

**`.tct` - the series, no pages.** The settings, the title, the synopsis, the
glossary and the character sheet. This is what you carry to the next chapter.

## 10.2 Every route in and out

| What | Where |
|---|---|
| Save project | File ▸ This chapter. Falls through to Save as if it has no path yet |
| Save as… | A native dialog, or a download where the machine has none |
| Open project… | A native dialog, or a file picker. The file is validated **before** anything is deleted |
| Download story context | File ▸ This series |
| Import story context… | File ▸ This series, and step 2 of the new-project wizard |
| Add pages | The wizard, **+ Add pages**, or drag and drop |
| Export pages | Step 7 |
| Export zip | Results |
| Translations JSON | The Translate dialog |
| Proofread report | The Proofread dialog |
| Manual template and import | Settings ▸ Translation engine, with **I'll translate it myself** on |
| The AI request and reply by hand | The Translate dialog |
| Fonts | Settings ▸ Fonts, stored outside every project |

## 10.3 Starting a new project

**Start a new project** clears the story - synopsis, characters, glossary, custom
box types - and keeps the technical settings: honorifics, medium, target, source,
and the engine configuration.

---

# 11. Things that are not there

Two things worth knowing about, because they are reasonable to expect.

**`honorifics` has no control.** It is on, and it is sent with every
translation. It lives under `context` rather than `settings` in the project
file, so the only ways to change it are editing `context.honorifics` by hand or
importing a `.tct` that carries a different value.

**The local text readers cannot be reached from the editor.** manga-ocr and
easyocr are installed, loaded at startup, and only used by the command-line
path. Read text in the editor is always a hosted vision model.

## Three defects found while writing this

Recorded here because they are small, real, easy to lose, and all three were
still true when this page was checked against the code a second time.

1. **The title is wiped on every load.** The project summary the browser reads
   does not include the title, so the field is filled with nothing and the next
   automatic save writes that back. It takes the `.tctp` and `.tct` filenames
   with it.
2. **An exported `.tct` carries the literal word "set" where the API keys were.**
   The browser exports the settings it was given, and it is given them masked.
   Importing that file writes those literals over real keys.
3. **`ocr_engine` is set to `ai` on every save** because the control it reads is
   no longer in the page, and the dead label above it is still there.
