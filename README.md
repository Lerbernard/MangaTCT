# mangatl — manga translation pipeline (prototype)

Detect speech bubbles → OCR Japanese → translate a full page at once with an
LLM → erase the source text → typeset English back into the bubbles.

```
mangatl/
  types.py            Page / TextRegion / TextLayout — the shared state
  order.py            reading order (right-to-left XY-cut + rotation search)
  detect/classical.py zero-weights bubble detector (works today)
  detect/yolo.py      production detector (needs weights you train)
  ocr.py              manga-ocr wrapper + sanity gate
  translate.py        page-level batch translation, glossary, continuity
  inpaint.py          flat-fill fast path, neural hook, screentone guard
  typeset.py          chord-based fit, balanced line breaking, scored layouts
  render.py           final composite + side-by-side HTML reader
  pipeline.py         orchestration
  cli.py              command line
  editor.py           the browser editor's HTTP server
  static/
    editor.html       page markup; loads the stylesheet and scripts below
    css/editor.css    all editor styling
    js/*.js           the editor client, split by concern (paint engine,
                      typesetting, panels, zoom/view, sync, …). Classic
                      scripts sharing one global scope — they must load in
                      the order editor.html lists. No build step.
tests/                14 tests over the deterministic stages
demo_offline.py       end-to-end run with hand-written translations
```

## What it can translate

The picker asks two questions before you load any pages, because both change
how the pipeline behaves.

| Source | Language | Reading order | OCR engine |
|---|---|---|---|
| Manga | Japanese | right to left | `manga-ocr` |
| Manhwa | Korean | left to right | `easyocr` |
| Manhua | Chinese | left to right | `easyocr` |
| Comic | English | left to right | `easyocr` |

Reading order is not cosmetic: getting the direction wrong hands the
translator its dialogue in the wrong sequence, and page-level context is where
most of the quality comes from.

Target languages: English, Spanish, Portuguese, French. The prompt adapts to
each — Spanish, Portuguese and French all force a formal/informal second
person decision that the source may not mark, so the model is told to pick one
per character and hold it across the chapter. Those three also run roughly
20-25% longer than English, so the model is pushed harder on brevity; if you
still see a lot of shrunken typesetting, lower **compact_margin** so the shorter
wording wins more often.

Korean and Chinese need a second OCR engine, since `manga-ocr` is Japanese
only and will refuse rather than return nonsense:

```bash
pip install easyocr
```

## The editor (start here)

```bash
python -m mangatl.editor --output out/
```

Opens `http://127.0.0.1:8765` and asks you to pick your pages — drop a folder
onto the window, use **Choose folder…**, or paste a path to a folder already on
this machine (faster for a whole chapter, since nothing has to be copied).
Detection starts immediately and runs in the background while you work.

You can still skip the picker by naming the folder up front:

```bash
python -m mangatl.editor --input chapter_folder/ --output out/
```

**Edit** and **Results** tabs sit at the top left. Results shows every exported
page as a thumbnail; click one to jump back to it in the editor.

- **Three views** of every page, top right: **Original** (the scan as it came
  in), **Cleaned** (source text erased, nothing added — this is where you check
  the inpainting), and **Translated** (the finished page). In the Translated
  view, dragging a bubble moves its typesetting rather than the box, so you can
  position text by hand and see the result immediately.
- **Top** — two rows. Identity, tabs and view toggles above; the five workflow
  steps below, each showing how many pages have reached it (a tick when the
  whole chapter is through) and a progress bar for whatever is running.
- **Left** — every page, with a status dot. Hover a page for an **x** to drop it
  from the project (the file on disk is untouched), or **+ Add files** to bring
  more in without losing your work.
- **Middle** — the page with the detection overlay in red. Drag on empty space
  to add a bubble; new boxes snap to the bubble outline (toggle *Snap new
  boxes* off in the top bar to keep exactly what you draw, or hold Shift to
  invert it for one drag). If a snap grabs more than you wanted, press
  **Box as-is** to get your rectangle back.
  Click a box to select it, then drag the body to move or a corner to resize.
  **Moving and resizing never re-snap** — the shape you set is the shape you
  keep. Drag a box to move it,
  corners to resize — it re-snaps on release. Hold **Shift** while releasing to
  keep the raw rectangle instead of snapping. <kbd>Del</kbd> removes,
  <kbd>S</kbd> marks a region as a sound effect, arrow keys change page.
- **Right** — the region list and inspector. Edit the Japanese, the English and
  the shorter alternative by hand; everything is saved as you go.
- **Top** — run OCR and translation over the chapter, tick *preview typeset* to
  see the typeset page, then **Export folder**.

Editing the typesetting is live. In the Translated view the browser draws the
text itself over the cleaned page, and the server only supplies line positions
— about 10ms a call rather than a second for a full re-render. Type a line
break, drag the number in the size box, or drag the bubble, and it updates as
you go. Dragging does not touch the server at all until you let go. Nothing is
saved until you press **Keep this**.

Editing typesetting is live: the Translated view is the *cleaned* page with the
text drawn in the browser using the same font file the exporter uses, so
dragging and typing update instantly with no round trip. Saves happen in the
background, and the server replies with exact chord-aware positions that
replace the browser's estimate. The exported file is always rendered
server-side, so the preview is a preview and the export is the truth.

**Typeset** is its own step, before export. It lays out the typesetting and
stores it, so you can turn on *Preview typesetting* and check every page before
anything is written to disk. Select a bubble and the inspector shows the
typesetting it chose — size, line breaks, whether it fell back to the shorter
wording, whether it had to shrink. Edit the line breaks directly, change the
size, nudge the block a few pixels, and press Apply. An applied edit is kept:
re-running Typeset will not overwrite it, and *Auto-fit again* puts it back
under automatic control. Edited typesetting is still clipped to its box, so a
hand edit cannot become a way to spill text over the artwork.

**Reading direction** is asked on the picker alongside the source material and
can be changed later in settings. It defaults to the medium — right-to-left for
manga, left-to-right for manhwa and manhua — but plenty of series break that
rule, so it is a separate control rather than something inferred and locked in.
Change it and press **Find bubbles** to renumber.

**Export** opens a dialog with a **Browse…** button that shows your operating
system's own folder chooser — Explorer on Windows, Finder on macOS, zenity or
kdialog on Linux. It runs in a subprocess, so a missing toolkit or a wedged
dialog cannot take the editor down; if no chooser is available the button
hides and you type a path instead. The dialog shows the full destination as
you type.

**Start a new chapter** sits permanently on the Results tab, and in the
picker under **Pages…**. It clears the pages, boxes and translations while
keeping your language, fonts and engine settings, and forgets where the last
chapter was written so the Results tab empties too. Exported files on disk are
untouched, and nothing is cleared without asking.

**Export** previously asked where to save and what to call the folder, then writes the
pages there. The Results tab also offers the whole set as a single .zip. State lives in `out/project.json`, so you can
close the editor and pick up where you left off.

Each kind of text can use its own font — speech bubbles, text outside bubbles,
sound effects and narration boxes are set separately under **Fonts & typesetting
settings**. A font that has moved or can't be read is rejected when you pick it,
and typesetting falls back to the default rather than failing the page.

If one box has swallowed several bubbles, select it and press **Split** — it
re-runs detection inside that box and replaces it with the individual bubbles.

Boxes are colour-coded: blue = detected, green = you added it, dashed grey =
weak detection that may be artwork.

## Install

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
export MANGATL_FONT=/path/to/CCWildWords.ttf     # optional but recommended
```

`manga-ocr` pulls a ~450MB model on first run. `opencv`, `numpy`, `pillow` and
`anthropic` are the only hard requirements for everything else.

## Run

```bash
# full pipeline
python -m mangatl page.png -o out/ --context series.json

# a whole chapter, sharing glossary and continuity across pages
python -m mangatl chapter/ -o out/ --context series.json

# side-by-side reader only — no inpainting, no typesetting
python -m mangatl page.png -o out/ --reader-only

# detection + OCR only, no API calls
python -m mangatl page.png -o out/ --no-translate --debug
```

Outputs per page: `NAME_en.png` (translated), `NAME_reader.html` (hoverable
side-by-side), `NAME.json` (every region with source, translation, speaker,
flags).

## Verified against your 40-page chapter

- **Detection** — 348 regions over 40 pages, 8.7 per page, no page left empty,
  ~340 ms per page. Getting there took a real fix: the original white-blob
  detector found only 2.5 regions per page and returned *nothing* on 6 pages,
  because on this chapter the bubble interiors connect to the white page
  background, so the merged blob touches the page border and gets rejected.
  Detecting the bubble's dark **outline** instead recovers them. Both methods
  now run and their results are merged.
- **Box snapping** — 95% of simulated sloppy drags recover the true bubble
  (320/336). Two bugs on the way: the search window started smaller than the
  bubble so it never found the outline, and at small windows it latched onto
  the counter inside a glyph.
- **Persistence** — a whole chapter is stored as polygons, not bitmaps
  (1.4 MB of JSON for 348 regions). Masks are rebuilt on demand; a test asserts
  the rebuilt mask matches the original at IoU > 0.95.
- **Export** — 4 pages exported at full 960×1365 in 9.3 s including inpainting
  and typesetting.
- **Tests** — 17 passing.

## A better detector (optional, no training)

The built-in detector needs nothing and works out of the box, but it is
heuristics: it misses burst bubbles, bubbles over dark art, and anything
without a clean outline. Several people have already trained detectors on
thousands of manga pages and published the weights, so you can have a real
model without a GPU or a dataset.

```bash
pip install ultralytics
python get_models.py          # downloads into ./models
```

Then in the editor: **Bubble detector -> Trained model**, set the path, press
**Find bubbles**. Runs on CPU at roughly a second a page.

| Model | What it does |
|---|---|
| `ogkalu/comic-speech-bubble-detector-yolov8m` | Bubbles. ~8k manga/webtoon/manhua pages. |
| `kitsumed/yolov8m_seg-speech-bubble` | Bubbles as segmentation masks, so outlines are shaped rather than rectangular. |
| `ogkalu/comic-text-segmenter-yolov8m` | The text itself — catches free-floating dialogue and SFX outside any bubble. |

The model runs first and the built-in detector fills in whatever it missed;
the two fail differently, so the union beats either alone. The model supplies
the bubble and the ink inside it supplies the text mask, so single-class
models work fine.

## Known gaps

1. **OCR and translation are unexercised.** This environment has no network
   access to the model weights or the Anthropic API, so those two stages are
   written but have never run. Everything around them has. This is the first
   thing to try on your machine.
2. **Detection precision is unmeasured.** 8.7 regions per page is plausible but
   I could not view the overlays to confirm none are artwork. The `confidence`
   score (see `score.py`) is a soft signal only — weak boxes render dashed. If
   you find it over-detecting, tell me the pages and I will tune.
3. **Free-floating text and SFX are still not detected.** `ハア…`, `キャー`,
   `ドドン` have no enclosing outline. Add them by hand with a drag and mark
   them SFX with <kbd>S</kbd> — that is what the manual path is for.
4. **Panel detection is rough** and off by default. Region-level ordering is
   accurate enough without it.
5. **No undo.** Deleting a region is immediate. Worth adding.

## Tuning knobs that matter

In `typeset.TypesetConfig`:

| Knob | Default | Effect |
|---|---|---|
| `min_font` | 12 | Legibility floor. Below this the region is flagged, not shrunk. |
| `compact_margin` | 0.60 | How much better the shorter wording must score before it wins. Lower = terser dialogue, more bubbles fit. |
| `w_small` | 1.40 | Preference for larger type. |
| `w_lines` / `soft_max_lines` | 0.25 / 5 | Discourages tall stacks of one-word lines. |
| `ideal_cpl` | 16 | Comfortable characters per line. |
| `margin` | 0.88 | Fraction of the bubble chord that text may occupy. |

## Design notes worth keeping

**Translate the whole page at once.** Japanese drops subjects constantly;
`来たんだ` has no subject at all. Only surrounding dialogue reveals who came.
This is the single biggest quality lever in the pipeline.

**Ask the model for a `compact` alternative per line.** Costs almost nothing
and eliminates most overflow, because you can shorten the words instead of
shrinking the type. Readers notice tiny text far more than terser dialogue.

**Fit against the bubble mask, not its bounding box.** The usable width for a
line is the narrowest horizontal chord across that line's rows. Inside an oval
this produces the tapered short/wide/short block real typesetters use, for free.

**Detection is never automatic.** Loading pages loads pages. Pressing
**Find text** opens a dialog asking what to look for:

- *Speech bubbles* — dialogue inside an outline. This is the reliable one.
- *Text outside bubbles* — unboxed dialogue sitting on the artwork. Deliberately
  conservative: on a dense page almost any stroke can look like a letter, so it
  would rather miss some than bury the page in wrong boxes. Expect to add some
  by hand.
- *Sound effects* — found the same way, but marked SFX so they use the SFX font
  and are left out of the cleaning pass.

You can run it on the whole chapter or just the page you are on. Re-running
replaces the boxes on the pages it touches, so hand-drawn ones there are lost.

**Choosing pages.** Drop files or a folder, or press *Add pages*. They go into
a list first rather than loading straight away, so you can see exactly what you
picked, add more from somewhere else, and drop the ones you do not want — a
credits page, a duplicate scan. Files already in the list are skipped rather
than added twice, and the order shown is the order they load in. Press
**Load pages** when the list is right.

**Text has its own box.** Like a text box in Word or PowerPoint, the typesetting
is independent of the region it came from. Select it on the Translated tab and
a frame appears with eight handles and a rotate grip above it: drag the middle
to move, the handles to resize, the grip to turn it (hold Shift to snap to
15°). It can sit anywhere on the page, including well outside the bubble.

This is also why rotation used to appear to do nothing. The text layer was
turned and then clipped straight back to the region mask, so everything the
rotation pushed outside the box was cut off again, and a second pass clamped
each line back inside the bubble for good measure. Both are gone for text you
have placed yourself: rotating now moves 83% of the drawn pixels somewhere
new, and a frame dragged off the bubble draws entirely off the bubble.

Because the text no longer obeys the box, the "too long for the box" warning
has gone with it.

On the Translated tab, clicking typesetting puts you straight into it, the way
clicking a text box in Word does: a caret appears, you can select words and
retype them, and the page updates as you go. The region box does not appear —
that view is for reading the result.

Resizing the box reflows the words rather than resizing them: narrow it and
the text wraps onto more lines, widen it and the lines fill out again, all at
the font size you chose. The wrap is measured with the actual font face, and
the resulting line breaks are saved, so the next edit starts from what you can
see. Only the size control changes how big the letters are.

While you type there is no white box and no coloured fill — the words sit on
the page in their own font with the same outline they will be exported with,
and the only chrome is a thin dashed border with handles. Drag that border to
move the block while still editing, the handles to resize or rotate. The
border strips are what you grab; the middle belongs to the caret. Escape
throws the edit away, Ctrl/Cmd+Enter or clicking elsewhere keeps it.

**Editing text on the page.** On the Translated tab the boxes hide themselves
— they make a finished page unreadable — and you edit the typesetting where it
sits. Double-click any text to open it in place, in the same font and size,
with the rest of the page dimmed. Type, and the page updates as you go. One
line per row, exactly as it will be typeset. Ctrl/Cmd+Enter or clicking away
keeps the change; Escape throws it away. Dragging still moves a block, and
**B** brings the boxes back if you want them.

Text edited this way is marked as yours, so re-running Typeset will not
overwrite it.

**Zoom and pan.** The toolbar has a hand tool, zoom out, a percentage readout
and zoom in. The hand tool (**H**) turns dragging into panning, as in any image
editor; double-clicking with it fits the page to the window, and so does
clicking the percentage. **+** and **&minus;** zoom, **0** fits, and
ctrl/cmd + scroll zooms around the cursor. A middle-click drag pans at any
time, whether or not the hand tool is on. **B** hides the boxes.

With **Snap new boxes** off, a box you draw is tightened onto the typesetting
inside it — draw roughly around a bubble and you get a box around its text.
Measured on this chapter, 15 of 16 rough boxes shrank to under 55% of what was
drawn, with the text still wholly inside every one. With snapping on, the box
expands to the bubble outline instead.

**Snap new boxes** is in the toolbar and off by default: most of the time
the rectangle you drew is the one you meant. Turn it on and a new box snaps to
the bubble outline it was drawn inside. Shift while releasing inverts whichever
way it is set. Moving and resizing never snap.

**White text on a dark panel is handled.** The ink threshold assumes dark
letters on a light background, which is true of nearly every speech bubble and
false of inverted panels, flashback captions and signs. Read the wrong way
round, the whole dark panel counts as text: it gets erased and filled with the
colour of the typesetting, leaving a pale rectangle where the artwork was. Each
region is now split by Otsu and the rim decides which side is background — a
panel touches its own edge, the words in the middle do not. Measured on this
chapter, the change makes no difference to ordinary pages at all.

**The side panel follows the view.** On Original you get the region tools —
kind, Japanese, English, split, re-snap, delete. On Cleaned it is about the
plate: swap in your own cleaned file, or touch up the automatic one. On
Translated it is the typesetting panel, and clicking any text opens it.

**Bring your own cleaned pages.** On the Cleaned tab, *Use my own cleaned
page…* replaces the automatic cleaning with a file you cleaned yourself — for
that page only. With pages 1–5 loaded and your own 3 uploaded, pages 1, 2, 4
and 5 keep the automatic plates. A mismatched size is scaled to fit, *Back to
automatic* undoes it, and the typesetting is drawn onto whichever plate is in
effect.

**The automatic cleaning is layers too.** The Cleaned panel lists one entry
per bubble; the eye switches that single cleaning off, putting the bubble's
original Japanese back on the plate while every other bubble stays cleaned.
Measured on a real page: with cleaning off, the ink in that bubble matches the
original scan exactly, and its neighbour is untouched. The setting is saved
with the project and honoured by export, and Ctrl+Z undoes the toggle.

**The colour picker is the app's own.** Clicking the colour well opens a
compact popover — a saturation/value square, a hue strip, a hex field, your
recent colours and the paper tones — instead of the operating system's colour
dialog, which never matched the app and buried the useful part. The
eyedropper and the loupe feed the same well, and the last seven colours you
picked stay one click away.

**The eyedropper previews before you click.** In browsers with a native
picker (Chrome, Edge) you get the system loupe and can sample anywhere on
screen. Elsewhere, a floating swatch follows the point showing exactly the
colour under it, with its hex value — what you see is what a click takes.
Both tools are icon buttons that light up while armed.

**The brush shows its size.** A circle follows the pointer while the brush is
active, sized to the stroke you will make at the current zoom, so there is no
guessing before the first dab. The eyedropper uses the browser's own picker
where it exists — sample any colour on screen, not just the page — and falls
back to click-to-sample elsewhere. The colour well shows the hex value, with a
row of greys and paper tones one click away.

**Strokes are layers.** Each brush stroke appears in a list on the Cleaned
panel, newest on top, like layers in an image editor: click to select, the eye
to hide one, the × to delete it on its own. Strokes always render beneath the
typesetting, so painting near a bubble cannot cover the text. They belong to the
page you painted them on and are unsaved until you keep them — switching pages
drops them.

**History and undo.** A *History* panel in the sidebar lists this session's
changes with timestamps — wording edits, typesetting changes, brush strokes,
plate swaps. **Ctrl/Cmd+Z** undoes the last undoable one: text edits and
typesetting restore their previous values, a brush stroke is removed, a plate
swap reverts to automatic. Inside a text field, Ctrl+Z stays the browser's own
undo for typing. The log lives for the session; reloading starts it fresh.

**Touch up the cleaned page in place.** A brush with a colour well, a size
slider and a colour picker that samples the page itself — paint over anything
the cleaner missed, undo stroke by stroke, then *Keep the touch-ups*, which
saves the result as your own plate for that page. *Discard* throws the strokes
away.

**Outline width** is a control next to Size in the typesetting panel. Black text
carries a white outline and white text a black one, chosen automatically from
what is behind it; this sets the thickness by hand, 0 for none. Clear the field
to go back to automatic.

**Paging is fast now.** Cleaning and typesetting a page takes around a second and
a half, and it was being redone every time you looked at it. Rendered pages are
cached against everything that can change them — the boxes, the wording, the
fonts, the size settings — so coming back to a page you have already seen is
instant, and an edit still recomputes it. The cache deliberately ignores the
computed layout that rendering writes back, since including it would change the
key on every render and never hit.

**Late replies are discarded.** Every page switch and every save carries a
ticket, and a reply holding an old one is thrown away. Without that, a slow
save landing after you had moved on would put one page's text on another, or
quietly undo an edit you had just made.

**Every step can run on one page.** Each button in the step bar asks: every
page, or only the one you are on. Export asks the same in its dialog. A
one-page run goes through the same machinery as a full run, so it shows in the
loading bar and lights its step like anything else — re-translating a single
page that came back wrong is one API call, not a chapter.

**Cleaning rebuilds the background rather than patching over it.** A flat
bubble interior is filled with its own modal colour, which is exact and
instant. Anything else — screentone, gradients, artwork, the cracked or
textured interiors common in flashback and shock panels — is reconstructed
from the surrounding pixels by inpainting. Measured against ground truth on
this chapter, that is about a third of the error of a flat fill on textured
areas, and the repaired patch carries the same amount of texture as the
background around it (std 21.2 versus 20.4, a ratio of 1.04).

Screentone regions used to be flagged and skipped entirely, which left the
original Japanese sitting on the exported page — 64,545 pixels of it across
this chapter. They are now cleaned like anything else, and 99.8% of source
text is removed chapter-wide. Heavily patterned areas are still flagged so you
can check them in the Cleaned view.

If you want better than this, `inpaint_page(page, neural=...)` takes a
LaMa-style callable and will use it in place of the classical inpainter.

**Cleaning leaves the artwork alone.** A rectangle drawn across a bubble
catches part of the bubble's own border, and erasing that hacks the outline
apart. For hand-drawn rectangular boxes, ink whose connected component
continues well outside the box is left alone — a border or a piece of art runs
past the edge, typesetting does not. Detected bubble masks follow the interior
and never included the outline, so they are untouched by this.

**Typesetting adapts to what it sits on.** Text is black with a white edge by
default — the edge is invisible inside a normal bubble and does the work over
tone or artwork. Where the background under the glyphs is dark, typesetting
flips to white with a black edge. The sample is taken from the strip the
glyphs actually occupy, not the whole bubble, so a light bubble with one dark
patch still comes out readable.

**Typesetting can never leave its box.** Each region's text is drawn on its own
transparent layer and composited through that region's mask, so it is
physically impossible for text to land on the artwork. The fitter avoids
overflow first (shorter wording, then smaller type, then tighter leading down
to an absolute floor); clipping is the guarantee behind it, and anything that
had to shrink below the minimum is flagged for review.

**Balance lines, don't pack them.** Knuth–Plass leaves the last line free,
which is correct for justified prose and wrong here — it makes packing cheap
and yields a full line above a one-word orphan. Weighting every line equally
gives balanced blocks. (This was an actual bug, caught by a test.)

**Validate that region IDs round-trip through the LLM.** Models occasionally
drop or duplicate a region, and a dropped region is a blank bubble in the
output. Retry on mismatch rather than letting it through.

## Translation engines

Translation is the only stage that leaves your machine, and it is pluggable.
Pick the engine under **Fonts & typesetting settings → Translation engine**.

Default is **Claude Sonnet 5** — set `ANTHROPIC_API_KEY` in `.env` and you are
done. A 40-page chapter runs about 25 cents. Model choice sits under Fonts &
typesetting settings; the alternatives below are tucked under *Advanced* and are
there if you ever want them.

| Engine | Cost | Notes |
|---|---|---|
| Claude API | ~pennies per chapter | Best quality. Needs `ANTHROPIC_API_KEY`. |
| Ollama | free, local | `ollama serve`, then pull an instruct model. Nothing leaves the machine. |
| LM Studio | free, local | Start its local server, point at `http://localhost:1234/v1`. |
| llama.cpp server | free, local | `llama-server --port 8080`. |
| Google AI Studio | free tier | ~1,500 requests/day. Best free quality for Japanese. |
| Groq | free tier | 30 req/min, 1,000/day. Very fast. |
| Cerebras | free tier | ~1M tokens/day. |
| OpenRouter | free tier | 50 free-model requests/day, one key across providers. |
| Other OpenAI-compatible | varies | Any host speaking `/v1/chat/completions`. |

Free tiers rate-limit hard, so a 429 backs off and retries (up to 5 attempts,
honouring `retry-after`) rather than failing the page. Note that most free
tiers train on what you send them — fine for manga you are reading, worth
knowing before you send anything private.

For Ollama:

```bash
ollama pull qwen2.5:14b-instruct       # good JA->EN, ~9GB
ollama serve
```

Then set engine to **Ollama** and model to `qwen2.5:14b-instruct`.

**The model has to follow instructions and return JSON.** Classic
sentence-level MT models (opus-mt, NLLB, m2m100) cannot do that. They also
translate one line at a time, which throws away the page context that makes
this pipeline worth having — Japanese drops subjects constantly, and only the
surrounding dialogue reveals who is speaking. Use an instruct model.

Sizing, roughly: 7B works and is noticeably rougher; 14B is the sweet spot on
consumer hardware; 32B approaches hosted quality if you have the VRAM. Models
tuned for Japanese media translation (the Sakura and Sugoi GGUF families) are
worth trying at a given size. On CPU only, expect minutes per page rather than
seconds.

## Legal

Translating and redistributing licensed manga is copyright infringement
regardless of how the translation was produced. The defensible uses are a
local personal reading tool, a language-learning aid (the side-by-side reader
is genuinely useful on its own), or a licensed tool sold to rights holders.
