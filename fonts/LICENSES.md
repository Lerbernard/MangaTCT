# The faces in this folder, and why these ones

Everything here is under the **SIL Open Font License 1.1**, which permits
redistribution inside software — including software that is sold — as long as
the licence travels with the font and the font is not sold on its own. mangatl
is GPL-3.0 and is downloaded and installed, so redistribution is exactly what
it does, and that is the one question every font in this folder has to answer.

| File | Family | Designer / source | Licence |
|---|---|---|---|
| `Anton-Regular.ttf` | Anton | Vernon Adams · Google Fonts | OFL 1.1 |
| `Bangers-Regular.ttf` | Bangers | Vernon Adams · Google Fonts | OFL 1.1 |
| `Chewy-Regular.ttf` | Chewy | Sideshow · Google Fonts | OFL 1.1 |
| `ComicNeue-Regular.ttf` `-Bold` `-Italic` `-BoldItalic` | Comic Neue | Craig Rozynski · Google Fonts | OFL 1.1 |
| `Gaegu-Regular.ttf` `-Bold` | Gaegu | Hanyang I&C · Google Fonts | OFL 1.1 |
| `GochiHand-Regular.ttf` | Gochi Hand | Huerta Tipográfica · Google Fonts | OFL 1.1 |
| `Jua-Regular.ttf` | Jua | Woowahan Brothers · Google Fonts | OFL 1.1 |
| `Kalam-Regular.ttf` `-Bold` | Kalam | Indian Type Foundry · Google Fonts | OFL 1.1 |
| `LuckiestGuy-Regular.ttf` | Luckiest Guy | Astigmatic · Google Fonts | OFL 1.1 |
| `NanumPenScript-Regular.ttf` | Nanum Pen Script | Sandoll · Google Fonts | OFL 1.1 |
| `PatrickHand-Regular.ttf` | Patrick Hand | Patrick Wagesreiter · Google Fonts | OFL 1.1 |

## The mark faces in `marks/`

These are not typesetting faces and are never offered in the font picker; they
supply the special characters a line can carry (♥ ★ 💢 ♪ ⁉ …) - see
`marks.py` and `typeset.mark_glyph`. Each is a small **subset** of an OFL 1.1
Google/Noto face, cut down to the few dozen characters the picker offers and
**renamed** (MarkEmoji, MarkSymbols, MarkMusic), because the OFL's Reserved
Font Name clause does not allow a modified copy to keep the name "Noto". The
OFL permits both the subsetting and the redistribution.

| File | Subset of | Designer / source | Licence |
|---|---|---|---|
| `marks/marks-emoji.ttf` | Noto Emoji (monochrome) | Google · Google Fonts | OFL 1.1 |
| `marks/marks-symbols.ttf` | Noto Sans Symbols 2 | Google · Google Fonts | OFL 1.1 |
| `marks/marks-music.ttf` | Noto Music | Google · Google Fonts | OFL 1.1 |

## What used to be here and is not

Three faces were removed on 2026-08-26. All three were the *right* choice
aesthetically, and none of them may be bundled in a program somebody downloads.

**`CCWildWords.ttf` — Wild Words, Comicraft.** A paid font: $49 a style, $139
for the family of four. The desktop licence expressly forbids app integration
and sharing; embedding in software is a separate and dearer licence, sold by
quote. Wild Words is the most widely used dialogue face in English manga
publishing, which is precisely why it was here.

**`AnimeAce.ttf`, `AnimeAce-Bold.ttf`, `AnimeAce-Italic.ttf` — Anime Ace,
Blambot.** Free to *use* for
comic work, including work that earns money, and the default face of most of
scanlation. But Blambot's terms prohibit redistribution under every free
licence. Their paid **Embedding** licence ($300 a family) covers software where
the end user cannot extract the font file — which a `.ttf` in this folder
plainly can be — so the tier that would actually apply is **Redistributive**,
sold only by quote.

**`Komika.ttf` — Apostrophic Labs.** Removed for a different reason: it is
widely described as free for commercial use, and no authoritative statement of
its *redistribution* terms could be found. The foundry is long defunct. An
unverifiable licence is not a licence, and this folder is not the place to
guess.

## If you own one of them

Put it in your own fonts folder in the app (Settings → Fonts) rather than here.
`typeset._font_dirs()` searches your uploaded fonts **before** the bundled ones,
and `default_font_path()` still names Wild Words and Anime Ace first — so a
licensed copy is picked up automatically and everything looks the way it did.
Nothing is lost by their absence except our right to hand them to other people,
which we never had.

## Adding a font here

Two questions, in order. Does its licence permit redistribution inside
software? Can you point at the sentence that says so? If either answer is no,
it belongs in the user's own folder, not in this one.
