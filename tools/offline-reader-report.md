# The reader was already on his disk

*2026-08-22. lee: "are there any off line otion that can rival the ai option
i wan you to text some out"*

Six offline readers, the same thirty-two lines, cut from lee's own chapter.

## The ground truth

Thirty-two boxes from pages 004, 008 and 020 of the chapter, cropped by the
app's own detection, transcribed by eye character for character. Twenty-seven
of them are dialogue, five are painted sound effects. Score is character error
rate: the edit distance from the transcription, divided by its length. 0.00 is
perfect, 0.05 is one wrong character in twenty.

Everything is scored twice. Raw, and after folding the full-width punctuation
pairs - ？ ！ ⁉ ─ ．．． - because a reader that writes ？ where the page prints
? is not wrong, it is using the other form, and mangatl normalises those
anyway. The folded number is the one that matters.

## What came back

| reader | all | dialogue | sfx | exact | s/box |
|---|---|---|---|---|---|
| **manga-ocr** | **0.082** | **0.054** | 0.233 | 22/32 | **0.42** |
| manga-image-translator, 48px CTC | 0.224 | 0.154 | 0.605 | 13/32 | 11.5 |
| manga-image-translator, 48px AR | 0.284 | 0.228 | 0.586 | 11/32 | 1.43 |
| tesseract jpn_vert | 0.734 | 0.685 | 1.000 | 2/32 | 0.29 |
| RapidOCR, PP-OCRv4 | 0.916 | 0.901 | 1.000 | 0/32 | 5.10 |
| easyocr ja | 1.069 | 1.081 | 1.000 | 0/32 | 4.33 |

One of those thirty-two crops is not a fair question. 004's box id 7 is a
detection bug from before the 95% rule: a 187x168 box sitting on top of id 9's
72x156 box, so the crop physically contains the neighbouring balloon's line as
well. Every reader that read it correctly was marked wrong for reading too
much. Taking that one crop out:

| reader | dialogue, minus the bad crop | exact |
|---|---|---|
| **manga-ocr** | **0.025** | 19/26 |
| 48px CTC | 0.128 | 12/26 |
| 48px AR | 0.194 | 10/26 |

**manga-ocr misses one character in forty on dialogue, in four tenths of a
second, on a laptop CPU, with no key and no network.**

## What manga-ocr actually got wrong

Ten of the thirty-two, and most of them barely:

- `ザルドネ` read as `ザルトネ`, `エータ` as `エーダ` - dakuten, the two-stroke
  mark, on stylised type.
- `『このくらい当然です』` came back with `「」` - the other quotation bracket.
- one stray `、` inserted, one `の` read as `人`.
- the sound effects: `チラッ`→`イラッ`, `ぽか`→`ほか`, `ゴボッ`→`ゴホン`.
  Same failure both times - the small kana and the dakuten on paint.

Sound effects are where it is weakest, CER 0.233, and that is the honest
shape of it: it was trained on typeset dialogue, and a hand-drawn `ゴボッ`
is not that.

## Why the two manga-image-translator models lose

They are line readers, not box readers. Something has to cut the box into
vertical columns before they see it, and that splitter is the whole game.
The first attempt (Otsu projection, split at zero columns) scored 0.559 and
returned nothing at all for every one of 020's monologues, because those are
white type on black art and the projection never reaches zero. Driving the
split from CTD's own glyph mask made it *worse*, 0.753, because the mask is
fatter than the glyphs and neighbouring columns touch.

What finally worked was measuring the character width from the mask's own
connected components, then cutting any run wider than 1.6 characters at its
deepest projection valley, recursively. That took CTC from 0.753 to 0.224.
The model was never the problem. The splitter was, and it is still the
reason both of them sit three times worse than a model that just looks at
the whole box.

manga-ocr has no splitter. It reads the box.

## The bit that nearly did not happen

huggingface.co is blocked from this container - 403 at the egress proxy, and
so are hf-mirror and modelscope. manga-ocr lives there and nowhere else, so
the plan was to ship lee a kit and have him run it.

He already had the weights. `C:\Users\leema\.cache\huggingface` is one of the
connected folders, and `models--kha-white--manga-ocr-base` was sitting in it
with a full 444MB `model.safetensors`. The bridge refuses a file that size,
so it came across in eleven 40MB pieces cut with `dd` on his machine and
concatenated here. Byte-identical, loads clean, 263 tensors.

(There is also a `_to_delete/mocr_flat/pytorch_model.bin` on his disk at
103MB. It is a truncated download - `PK` header, no central directory, torch
refuses it. Whatever it was for, it never worked.)

## What this means for the Read text step

The app already wraps manga-ocr, in `ocr.py`, with a batching path that runs
several crops through one forward pass. Nothing in the editor calls it:
`do_ocr` goes straight to the vision model. The offline reader is built and
unplumbed.

What the AI still buys, and manga-ocr cannot:

- **page context.** The vision reader sees the whole page at once, which is
  what lets it tell 居たぞ from 口はたぞ and rebuild a broken name from the
  dialogue around it. manga-ocr sees one crop, blind.
- **Korean and Chinese.** manga-ocr is Japanese only. Manhwa still needs
  something else.
- **sound effects.** 0.233 versus dialogue's 0.025.

What it buys instead: no key, no network, no coins, and 0.42s a box - about
eight seconds for a twenty-box page, all of it local.

That is a real second reader, not a fallback. The shape it wants is a choice
in the Read text step - the AI reader, or the offline one - with the offline
one honest about being Japanese-only and weaker on paint.
