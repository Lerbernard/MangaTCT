"""What a box is, decided from what the OCR read out of it.

lee, after DB++/COO was measured against every cheaper way of labelling boxes:
*"do this I build the reordered pipeline, since that's where the idea pays off
regardless of which OCR you use"*.

## THE ORDER IS THE WHOLE IDEA

Today the pipeline runs

    detect (and label)  ->  OCR  ->  translate

and the labelling in step one is done by a second neural net, DB++/COO, whose
entire job is to say which boxes are painted sound effects. That costs 116MB
and 2.4-3.9 s a page.

Reordered, it runs

    detect  ->  OCR everything  ->  label from the text  ->  translate

and the label costs **nothing**, because `ocr.ocr_page` already reads every
region on the page -- sound effects included -- before anything is translated.
The work was always being done; it was just being thrown away.

## AND THE SIGNAL IS GRAMMAR, NOT LEGIBILITY

The first version of this idea was "clean readable Japanese means dialogue",
and that is wrong: ガチャ is perfectly clean readable Japanese. Measured over
257 boxes with a recogniser, what actually separated them was not confidence
but CONTENT --

    boxes COO calls paint   median 1 character,  0.00 kanji,  0.00 kana
    boxes COO calls text    median 3 characters, 0.50 kanji,  0.29 kana

-- and the reason is typographic rather than statistical. A Japanese sentence
carries kanji and it carries particles, は を に が で と, the glue that makes
it a sentence. A painted sound is katakana with no grammar in it: ドドド, ザァァ,
ガチャ. Nothing about how cleanly it reads distinguishes them; everything about
what is IN it does.

## WHAT IS MEASURED HERE AND WHAT IS NOT

The 257-box measurement above is real and it is what the rule is shaped
around. The THRESHOLDS are not tuned on this chapter, because the recogniser
that could read it -- manga-ocr, which handles vertical type natively -- has
weights this sandbox cannot fetch, and the one that was available reads along
a line and returned `…9舛ゆささめダ是性叶公` for an ordinary balloon.

So this ships OFF, with the rule written from the typography and tested
against hand-written strings. Turning it on once there is real OCR text to
sweep against is one setting.

Worked, by hand, on lines this chapter actually contains:

    ガチャ ドドド ザァァ スッ キョロキョロ ぶぶぶっっっ   sound
    こっちの部屋は自由に使ってください                speech (kanji)
    第三章  悪女見習いさん  血が…                   speech (kanji)
    はい                                     speech (は)
    大丈夫ですか                                speech (kanji, です)

**AND ONE IT GETS WRONG.** つづく -- "to be continued" -- is three hiragana
with no kanji and no particle in it, and reads as a sound. It is written out
here rather than special-cased, because a stop-list of words that are not
effects is a list that grows forever and never covers the next series. It
costs one box at the end of a chapter, outside every balloon, and lee on this
exact split: *"dont worry about teh outside text and sfx distention too much
... but we need to ghave te bubble text sorted out"*.

## AND THE BALLOON STILL OUTRANKS IT

This is only ever asked of a box with nothing drawn round it. A box inside a
balloon is dialogue whatever it says -- that has been lee's rule since the
manhwa and it is not up for renegotiation by a text classifier.
"""
import re

#: Kanji. A sound effect essentially never carries one; a sentence usually
#: does, and one is enough to settle it.
KANJI = re.compile(r"[一-鿿㐀-䶿]")
#: THE GLUE OF A SENTENCE.
#:
#: Particles and copula endings. These are what a painted sound does not have
#: and a line of dialogue can hardly avoid: を に は が で と も の から まで,
#: and the sentence-final ね よ か な わ ぞ ぜ. Written as a set of single
#: characters rather than a parser, because the input is one OCR line and a
#: parser would be pretending to a certainty the OCR has not got.
PARTICLES = set("をにはがでともの")
#: ...and the endings, which are separated because a lone を in the middle of
#: an effect is nothing and a trailing ね is a person talking.
ENDINGS = set("ねよかなわぞぜだですますました")
#: How long a string of kana with no grammar in it may be before it is a
#: sentence the OCR failed to punctuate rather than a noise. Sound effects on
#: this chapter run 1-6 characters; the longest painted one is ぶぶぶっっっ at
#: eight. Twelve leaves room and still refuses a swallowed sentence.
SFX_MAX = 12
#: Marks that are not writing in either direction -- they carry no evidence,
#: so they are stripped before anything is counted rather than counted as
#: kana. `々` and `ー` are held back deliberately: a repeat mark and a long
#: vowel are what an effect is MADE of.
STRIP = " \t\r\n。、．，!?！？…‥・「」『』（）()〜~-"


def looks_like_a_sound(text: str, least: int = None) -> bool:
    """Does this OCR line read as a painted sound rather than as speech?

    Four questions, and the order is the content:

      1. **Nothing readable at all is paint.** A box the recogniser returns
         nothing for held no letters it knew -- which is what a brush stroke
         is. This is also the honest answer when OCR failed: the box gets
         painted out rather than handed to a translator as an empty line.
      2. **Any kanji is speech.** One is enough. A painted sound is written
         in kana because that is what a sound is.
      3. **Any grammar is speech.** A particle or a sentence ending is a
         person talking; ガチャ has neither.
      4. **And anything long is speech**, whatever else it holds, because
         twelve characters of kana with no grammar is a sentence the
         recogniser mangled rather than a noise.
    """
    least = SFX_MAX if least is None else least
    if not text:
        return True
    bare = "".join(c for c in text if c not in STRIP)
    if not bare:
        return True
    if KANJI.search(bare):
        return False
    if any(c in PARTICLES or c in ENDINGS for c in bare):
        return False
    if len(bare) > least:
        return False
    return True


def kind_from_text(kind: str, text: str, in_balloon: bool,
                   least: int = None) -> str:
    """The kind of a box, once its text is known.

    `in_balloon` is the balloon search's answer and it wins outright -- see
    the module docstring. Everything else is `looks_like_a_sound`.

    Returns the kind to use, which may be the one that came in: a box already
    labelled by a specialist is not overruled here unless it has nothing drawn
    round it.
    """
    if in_balloon:
        return "bubble"
    return "sfx" if looks_like_a_sound(text, least) else "freefloat"


def relabel(regions, least: int = None) -> int:
    """Re-decide every region's kind from what was read out of it.

    Returns how many changed, which is what a caller logs. A region whose
    `own_text` is set is somebody's own box and is never touched: nothing was
    read out of it because there was nothing under it to read, and calling
    that paint would be the worst possible answer.
    """
    moved = 0
    for r in regions:
        if getattr(r, "own_text", False):
            continue
        was = r.kind
        r.kind = kind_from_text(was, getattr(r, "src_text", "") or "",
                                getattr(r, "bubble_mask", None) is not None,
                                least)
        moved += (r.kind != was)
    return moved
