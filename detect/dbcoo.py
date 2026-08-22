"""Two specialists instead of one generalist, and never a weld between them.

lee, after the head-to-head over 23 pages of manga: *"its very ovious what
needs to be doen these 2 are very realiable and better at detecting each of
their own secments"*, *"if you can get db net to merge teh boxes in on bubble
and have both run i think it will litherly be perfect"*.

Measured, and he is right:

    approach                          missed   junk   wrong   s/page
    comic-text-detector alone              5     13      18     2.94
    DBNet (both ways) + DB++/COO           4      4       8     7.60

Fewer misses AND under a third of the junk. What the current pipeline gets
wrong is almost all one thing -- twelve of its thirteen junk boxes are the
sound-effect family, and cropped they are a hand, a face, two eyes, a fence
rail, flower marks. Neither specialist puts a box on any of them.

## comic-text-detector does not leave

`inpaint` skips a region whose `text_mask is None`, three times over. DBNet
and DB++ both return rectangles and nothing else, so a page detected by them
alone would not clean -- not badly, not at all. So CTD's `seg` head still runs
and every box built here takes its mask from `comictext.page_text_mask`, by
exactly the recipe the block loop uses: the page mask inside the box, falling
back to plain ink where the mask found nothing.

That is the honest cost. 2.94 for the mask + 5.22 for DBNet read both ways +
2.38 for COO = **10.54 s/page** against 2.94 today, for ten fewer corrections
on 23 pages.

## Two pools, and the reach that goes with each

lee, of the first attempt: *"the weld are horible, sfx and outide ext shodu
not be welded and bubble text shoud only weled to text very close to them"*.

Both halves are here and the first one is free, because the pools arrive
already separated: `onomatopoeia` returns paint and `dbtext` returns writing,
and no reach is ever allowed to cross between them. The second half is the
reach itself -- dialogue joins only what is very close, which is why the text
pool runs at 0.10 of a mark sideways and 0.08 down, where the sound effects
get 0.3 either way because one effect's strokes are scattered.

Measured over the chapter, groups that swallow two separate texts:

    one pool,  reach 0.15/0.10        6 welds  (4 of them mixing kinds)
    two pools, text 0.10/0.08 sfx 0.3 2 welds  (0 mixing kinds)

and both of the two left are one sound effect that the ground truth had cut
in half -- ザァァ counted as ザ plus ァァ, ギョロギョロ as its two columns.
**No group on 23 pages joins two things that are really two things.**

Granularity comes out at 1.17 boxes per site against comic-text-detector's
1.06, with 223 of 226 sites found against its 221.
"""
import cv2
import numpy as np

from ..models import Page, TextRegion

# How far one mark reaches for another, as a share of the SMALLER mark, in
# `comictext.reach_groups` -- the app's own rule, not a second copy of it.
#
# TEXT joins a column of a balloon to the next column of the same balloon and
# to the ruby printed beside it. It was 0.10/0.08 for one turn and that was
# too tight -- lee: *"the meging need to be better ... 4 shoud be one outside
# text box for example"*, with 妬け / ちまう / なぁ arriving as three boxes and
# 正直 split off its own sentence. Swept over the chapter at 1280:
#
#     reach        boxes per site   groups swallowing two texts
#     0.10 / 0.08          1.17                   2
#     0.20 / 0.15          1.09                   2
#     0.30 / 0.25          1.07                   9
#
# 0.20/0.15 is where the joining stops being free: a third of the remaining
# fragments go and not one new text is swallowed, and the next step up costs
# seven.
#
# SFX is loose because one painted effect is scattered strokes, and because
# the pool cannot reach dialogue however far it goes.
TEXT_X = 0.20
TEXT_Y = 0.15
SFX_X = 0.30
SFX_Y = 0.30
# Two groups from the two pools describing the same writing. Not a weld --
# a weld joins two texts, this drops one of two boxes on one text -- so it is
# resolved by plain overlap and the bigger box wins.
SAME = 0.60
# BOTH MODELS SAW IT, SO SOMEBODY DREW IT BY HAND.
#
# lee, reading the two detectors side by side on page 008: *"as you can see
# that sometime some text are found by both detectors these text are always
# outside text so taht whou help with labbling"*.
#
# The mechanism is why it works. DBNet reads TYPE and DB++/COO reads PAINT, so
# each of them alone is a statement about which of the two a piece of writing
# is -- and the writing they agree on is the writing that is both, which is
# hand-set type laid straight on the artwork. On this chapter the overlap is
# ほか ほか ほか, また / グロウさん / ね, 店主, そんなので足りるかよ: every one
# outside a balloon, and every one a line somebody has to translate rather
# than a noise to paint out.
#
# `OVERLAP` is how much of a text box COO has to claim before it counts as
# agreement. `INSIDE_SFX` is the exception lee's rule needs and the reason it
# is not simply "both models saw it": a painted effect can have one character
# clean enough for DBNet to read -- the ぶ of ぶぶぶっっっ on 003, the ぶ of
# ぶるる on 016 -- and that character is agreement about a fragment of paint,
# not about hand-set type. A text group that sits mostly INSIDE a bigger
# sound-effect group is that fragment, and it is left to the effect.
OVERLAP = 0.30
INSIDE_SFX = 0.70
# ...and "inside" has to mean inside something BIGGER, or the test eats its
# own tail: the sound-effect group that agrees about ほか *is* ほか, so the
# text box sits 100% inside it and every agreement would read as a fragment
# of paint. The ぶ of ぶぶぶっっっ is a quarter of its effect; ほか is all of
# its own box. Twice the area is the line between them.
BIGGER = 2.0
# A box bigger than this share of the page is a panel, not writing.
PAGE_CAP = 0.12
# HOW MUCH ROOM ROUND THE WRITING, and it is a share of the box rather than
# a number of pixels.
#
# lee: *"also boxes are cropping some of the text add some padding"*, with
# 正直 cut through its ruby and 中は異常なかった shaved down one side.
#
# Two pixels was the block loop's number and the block loop was not the thing
# that needed it: comic-text-detector's boxes come off a pixel MASK of the
# ink, so they already hold every stroke. DB's come off a shrunk polygon
# pushed back out by a fixed ratio, and what the ratio misses is exactly what
# sits outside the main column -- Japanese ruby, at about 40% of the glyph
# size, printed hard against the text it reads for.
#
# So the pad scales with the box: a caption gets a caption's margin and a
# two-character aside gets a small one. Floored at 3px so a tiny box still
# gets something, capped at 14 so a full-page effect does not swallow its
# neighbours.
PAD_SHARE = 0.045
PAD_MIN = 3
PAD_MAX = 14
# ...AND THEN THE BOX IS GROWN TO THE WHOLE OF WHATEVER IT IS CUTTING.
#
# Padding alone cannot fix a crop, because the right amount is not a
# property of the box -- it is however far the glyph it clipped happens to
# extend. lee, twice: *"boxes are cropping some of the text add some
# padding"*, and again after the pad went in.
#
# The mask knows. `comictext.page_text_mask` marks every inked pixel on the
# page, so a box that clips 誇 through the middle is a box overlapping a mask
# blob that continues past its edge, and the blob's own extent is exactly how
# far to grow. Same idea as `_grow_to_the_stroke` in `comictext`, done
# against the page mask rather than against a threshold.
#
# `GROW_TOUCH` is how much of a blob has to be inside the box before the box
# owns it -- a fifth, so a glyph clipped in half is claimed and a neighbouring
# balloon's edge grazed at the corner is not. `GROW_CAP` stops a runaway: a
# blob that would grow the box by more than half its own size is not a
# clipped letter, it is the artwork the letter is sitting on.
GROW_TOUCH = 0.20
GROW_CAP = 0.50
INK = 110          # the fallback when the page mask found nothing in a box
MIN_INK = 20       # ...and how many pixels of it make a region worth keeping


# HOW FAR A BOX MAY REACH FOR WRITING IT IS MISSING.
#
# lee: *"u wan to use teh mask to extend boxes that are alread made so that
# they fill the whole etxt like in this box, it shou only extant ontext that
# is relatively close like one text chatrater away far, and it shoud only
# extaned to text taht isnst alraey in a box so no encrocing in another box"*.
#
# Three rules and all three are his.
#
# **One character.** The reach is measured in units of the box's OWN
# characters -- the median size of the mask blobs it already holds -- so a
# caption reaches a caption's distance and a two-character aside reaches a
# small one. Not a pixel count: the same chapter scanned at another
# resolution would need a different one.
#
# **Only writing nobody owns.** A blob whose centre already falls inside
# another box belongs to that box, and this pass never takes it. That is what
# stops two boxes on one balloon eating into each other.
#
# **And it repeats.** 情報は sits one character from こういう, and ません sits
# one character from 情報は -- so one pass reaches the first and not the
# second. The box grows and asks again, up to `GROW_ROUNDS`, which is what
# lets a run of writing be followed to its end without ever making a single
# jump longer than one character.
GROW_NEAR = 1.15         # ...of the box's own median character
GROW_ROUNDS = 6
GROW_BLOB = 40           # a mask blob smaller than this is a speck


# A BOX ONLY comic-text-detector BELIEVES IN HAS TO SHOW ITS LETTERS.
#
# lee, of the fifteen junk boxes with the mask drawn over them: *"the middle
# path is one line: keep a CTD sfx box only when COO is silent and the box
# passes the balloon test or has real glyph structure. I'd want to measure it
# rather than guess"*.
#
# Where the junk lives is not in doubt and has not changed: of 241 boxes on
# the chapter, sixteen are comic-text-detector's own `sfx` family with nothing
# from COO on them, and **eleven of those sixteen are the artwork** -- a fence
# rail, two hands, a face, two flower marks, a chin line, a shoulder, two
# eyes, a rail. Every other cell of the table is nearly clean: 113 boxes CTD
# calls `bubble` hold one bad box between them, 40 `narration` hold one, and
# 44 that COO does agree with hold one. So one rule over one cell is the whole
# question.
#
# ## FOUR MEASUREMENTS, AND ONLY ONE OF THEM SEPARATES ANYTHING
#
# Over those sixteen boxes, real against artwork:
#
#     measure          real                       artwork
#     mask fill        0.18-0.38                  0.13-0.37     no
#     stroke width     0.17-0.45                  0.21-0.59     no
#     blob escape      0.00 (one at 0.34)         0.00          no
#     balloon/wall     1 of 5                     3 of 11       WORSE
#     bodies of ink    15, 17, 3, 1, 1            4, 3, 2, 2, 1  yes, partly
#
# The balloon arm of lee's rule is measured and it is **off**, and this is why:
# on this cell it fires for one real box (014's white zigzag, which happens to
# sit against a panel edge) and for three of the artwork ones (a rail and two
# eyes, all of them framed by drawn lines). Run end to end it changes not one
# miss and puts one junk box back. It is left wired as `SFX_KEEP_WALLED`
# because the reason it fails is about artwork being full of drawn edges
# rather than about the test, and another chapter could sit differently.
#
# What does work is counting BODIES: character-sized blobs of ink in the mask.
# A line of writing is many similar marks and artwork is one shape, and the
# split is total where it lands -- 001's credits strip has 15 and 002's
# hand-lettered こういう情報は規制されません has 17, against a ceiling of 4
# for every one of the eleven artwork boxes.
#
# ## AND IT DOES NOT SAVE EVERYTHING, WHICH IS THE HONEST PART
#
# Three of the five real boxes are one mark each -- 007's せっ, 013's white
# scribble, 014's zigzag -- and a single painted stroke is a single blob in
# exactly the way a hand is. No count separates those from the artwork,
# because at one blob there is nothing left to count.
#
# ## AND IT IS ON, WHICH IS LEE'S CALL AND NOT A MEASUREMENT
#
# The trade, put to him twice:
#
#     bar   missed   junk   what it means in the editor
#      0         4     15   delete a stray box now and then
#      5         6      4   notice a line went untranslated
#
# First *"go back to this CTD + COO labels (before)"*, and then, having seen
# the page with both: *"this + this rule (now)"*. So the bar is 5 and the pass
# runs. Eleven fewer rectangles to clear off every chapter is worth two sound
# effects that have to be drawn by hand, and 013's scribble and 014's zigzag
# are the two -- both single strokes, both real type, and both gone.
#
# `glyphs=0` at the call puts it back the other way for one run without moving
# anything, and one number here does it for good.
SFX_GLYPHS = 5           # ...bodies of ink before an unclaimed box is writing.
                         # 0 is OFF; 5 is the measured bar. See above.
SFX_GLYPH_AREA = 40      # ...and how big a body has to be to be one
SFX_KEEP_WALLED = False  # the balloon arm, measured and off. See above.
# ...and whether a rectangle holding two pieces of writing is split into two.
# lee: *"teh box merging shou not happen"*. See `detect_ctd_sfx`.
SPLIT_TEXTS = True
# ...AND THE SPECIALIST IS ASKED HOW MANY EFFECTS ARE IN THERE.
#
# Same complaint, and the hard half of it: 008's ガチャ ガチャ ガチャ arrives
# from comic-text-detector as ONE 434px rectangle. Three things were measured
# against it and two of them cannot work:
#
#   the sound-effect pool's reach   swept 0.30 -> 0.20 -> 0.12 -> 0.06 -> 0.
#                                   The widest sfx box moves by ZERO pixels.
#                                   The weld is not this route's to undo.
#   `_two_texts_in`, the app's own  fires on nothing. It looks for a diagonal
#     staircase test                pair or a stacked one, and three effects
#                                   in a row share every row and stack nowhere.
#   an empty-band split             the bands are 0.19 of one character on
#                                   008 and 0.04 on 007, against 0.45 INSIDE
#                                   003's ひゃあぁ, which is one effect. The
#                                   ranges are the wrong way round.
#
# What does work is asking DB++/COO, which detected each effect separately
# before anything grouped them: 008's rectangle holds three of its polygons,
# 007's ゲホ ゲホ holds two, and every effect that really is one holds one.
# So a claimed box covering two or more of COO's own pieces is replaced by
# those pieces.
#
# `SFX_PIECE_IN` is how much of a piece has to lie in the box before it counts
# as one of the things in it -- a neighbouring effect that merely grazes the
# rectangle is not what the box was drawn around.
SPLIT_SFX = True
SFX_PIECE_IN = 0.60
# HOW MUCH OF A BOX OF WRITING HAS TO SIT INSIDE A DRAWN BALLOON.
#
# For `detect_m109`, where the balloon is a shape the model segmented rather
# than a run of paper a Canny pass inferred. A share of the TEXT box, because
# that is the question -- is this writing in that balloon -- and a balloon is
# always the bigger of the two.
#
# 0.60 rather than something near 1.0 because the two rectangles come from two
# heads of the same net and their edges do not agree to the pixel: a column of
# type that runs to the balloon's inner edge lands a few pixels outside it.
# Nothing on the chapter sits between 0.6 and 1.0 by accident -- writing is
# either in a balloon or nowhere near one.
IN_BALLOON = 0.60
# ...and whether comic-text-detector is asked to fill the margins the
# Manga109 model does not annotate. See `detect_m109`.
FILL_GAPS = True
# A BOX ROUND OTHER BOXES IS A BRACKET, NOT A PIECE OF WRITING.
#
# lee, over 014's shop panel: *"alaso removethe bigger box that are around
# ground like this"*. AnimeText answers once per line of writing AND once
# round the lot, and the outer answer is the one to drop.
#
# `NEST_IN` is how much of a smaller rectangle has to lie inside the bigger
# one to count as held by it. `NEST_LEAST` is two rather than one on purpose:
# one is the duplicate case -- two answers about a single line -- which
# `_drop_duplicates` settles by keeping the better box, and dropping the
# bigger of those blindly would throw away the box that holds the whole of a
# clipped word.
NEST_IN = 0.70
NEST_LEAST = 2

# THE TWO RULES LEE ASKED FOR BY SCREENSHOT, both measured on his 39-page
# chapter (2026-08-20): *"fix these  the double bubble ,a nd bad bubble if
# possibel"*.
#
# THE BAD BUBBLES were embroidery: eight rosettes on the dresses of 004, a
# leaf vine on 011, chevron trim on 015/022/024 - twelve boxes of clothing
# pattern the model called text. What they have in common is measurable: the
# CTD seg head has NO ink in any of them (`regions_from` kept them alive
# through its dark-ink fallback, and dark embroidery on a white dress is
# nothing but dark ink), and the sound-effect specialist does not claim them
# either. Two witnesses silent = artwork. Real writing that also fails the
# seg head - 013's hand-drawn breaths - is vouched for by COO at 0.29-0.97
# cover against the junk's uniform 0.00, so the threshold has a margin of
# three. The one real box this costs on 39 pages is 039's tiny 悪女 label
# drawn on a sandal, which every model on the machine is silent about;
# CRAFT was tried as a third witness and could not see it either (its only
# vote at 4x upscale was FOR a rosette).
WITNESS_VOUCH = 0.10
# THE DOUBLE BUBBLE is one piece of writing answered twice - ちから boxed
# inside 癒やしの力, きょう inside its column, a tight になります inside the
# same line plus margin. Sixteen nested pairs on the chapter, and which box
# should die is not a fact about SIZE: 020's tight inner box is the right one
# and 038's tight inner box is the wrong one. It is a fact about INK. The
# kids' union held 0.85-1.00 of the parent's seg ink when the parent was
# padding, and 0.03-0.57 when the kids were fragments; 0.72 sits between the
# ranges with a margin of 0.13 on one side and 0.15 on the other.
ABSORB_IN = 0.58         # how much of a box must lie inside another to count
SAME_INK = 0.72          # kids holding this much of the parent's ink kill it


def glyph_bodies(tmask, box, min_area=SFX_GLYPH_AREA) -> int:
    """How many character-sized bodies of ink this box holds.

    Plain connected components over the page mask inside the rectangle, with
    specks dropped. Deliberately not `glyph_points`: that one throws furigana
    away to measure a direction, and here every mark counts.
    """
    if tmask is None:
        return 0
    x0, y0, x1, y1 = [int(v) for v in box]
    # Clamped at ZERO and nowhere else. A slice past the right edge is
    # clipped by numpy and needs no help; a NEGATIVE one is not -- it counts
    # from the far side of the page, so a box hanging off the left edge would
    # be measured against the right-hand margin instead of against itself.
    x0, y0 = max(0, x0), max(0, y0)
    m = (tmask[y0:y1, x0:x1] > 0).astype(np.uint8)
    if not m.any():
        return 0
    n, _lab, st, _c = cv2.connectedComponentsWithStats(m, 8)
    return int(sum(1 for i in range(1, n)
                   if int(st[i, cv2.CC_STAT_AREA]) >= min_area))


def _share(a, b) -> float:
    """How much of `a` lies inside `b`, as a share of `a`."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy / float(max(1, (a[2] - a[0]) * (a[3] - a[1])))


# A COLUMN OF VERTICAL JAPANESE STARTS AT THE TOP, AND SO DOES THE NEXT ONE.
#
# lee, over a screenshot with the two top edges drawn on it: *"these boxes
# shoud not merge, teh detector shodu look at the hight of the top of teh text
# boxk to detecmin if tehy shodu merge or not"*.
#
# That is a typographic fact and not a heuristic. Vertical Japanese is set
# from the top of the column down, so every column of ONE block of writing
# begins at the same height; a second thing said, set lower in the same
# balloon, begins at a different one. そうだ / ちょっとだけ外に / 出てみたい
# んです all start at the top of the plate, and もちろん しっかり / フードは
# 被るので starts a third of the way down. Nothing about the GAP between them
# separates those two -- they are as close as any two columns of one
# sentence -- and the tops separate them outright.
#
# The tolerance is a share of the taller column, so a short trailing column
# ("...けど" alone) still joins the sentence above it, and a block set half
# way down the plate does not. Ruby is why it is not tighter than this: a
# ruby column sits beside its kanji at 40% the size and hangs slightly low.
TOP_TOL = 0.22
# ...AND ONE BLOCK OF WRITING ALL FACES THE SAME WAY.
#
# lee: *"soemthing to kow is that bubble and outise text will always face teh
# same way so if a bunch of text is facing one way and another is facing a
# difent way its not the same text box"*, after *"the etxt are not even
# ratated teh same way"*.
#
# This is the discriminator the shape tests could not be. 004's 悪女見習いさん
# runs diagonally along the bottom of a balloon and its bounding box is
# neither a column nor a run, so nothing about width, height, gap or top
# edge separates it from the type set inside the same balloon. The GLYPHS
# separate it outright: set type is square to the page and hand-set type is
# not.
#
# Measured as the median of `minAreaRect` over every character-sized mask
# blob in the box, folded into 0-45 degrees (a square is square at 0 and at
# 90). Over every box DBNet finds on three pages, the median is **0.0** --
# set type is square to the page and stays square -- and the tilted ones run
# 7 to 15. Five degrees is well clear of both.
#
# AND IT IS OFF, because measuring it on the real boxes says it cannot work
# HERE. On 004, the page it was built for:
#
#     tilt_tol   boxes on the page
#      off              13     <- right
#      12.0             14
#      10.0             14
#       5.0             15
#
# Every tolerance costs boxes and none of them buys the one it was for. Two
# things go wrong at once. The balloon holding 心配ご無用 / 任せておけば /
# いいんですよ comes apart, because a column with one merged blob or a piece
# of ruby in it measures a few degrees off and that is the whole budget. And
# 悪女見習いさん is never separated, because **DBNet does not hand it back as
# its own box** -- it arrives fused to the column beside it, and a rule about
# which boxes may JOIN cannot split a box that was never two.
#
# lee's rule is right and this is the wrong place to apply it. Where it would
# work is inside `dbtext`, on DB's own polygon, before anything is grouped --
# splitting one detection into two by the angle of its glyphs. That is a
# change to the detector's output rather than to the grouping, and it wants
# its own measurement.
#
# Left wired and defaulted off, with `_glyph_tilt` kept: the measurement is
# sound (median 0.0 for set type over three pages, 7-15 for hand-set type)
# and the next attempt should start from it rather than re-derive it.
TILT_TOL = None
TILT_MIN_GLYPHS = 3
TILT_MIN_AREA = 60


# THE ANGLE THE WRITING RUNS AT, MEASURED OFF THE MASK.
#
# lee: *"for teh angle have a custom agnle finder that add point at points in
# tyhe yellow and make s a mean line and that line shoud be teh angle"*.
#
# A point at every glyph, and the direction from each point to its nearest
# neighbour -- which is the way the writing STEPS, one character at a time.
# The dominant direction is the angle of the run.
#
# Three earlier attempts measured the angle of the LETTERS and all three
# broke on the same thing: a Japanese glyph is square by design, so
# `minAreaRect` on one returns an arbitrary angle and a third of a perfectly
# typeset balloon reads as tilted. The arrangement has an angle even when the
# characters do not.
#
# Fitting ONE line through every point does not work either, and that was the
# first thing tried: a block of vertical type is a GRID of centroids, several
# columns wide, and its principal axis is meaningless (34px of spread, 100
# degrees). Nearest-neighbour steps stay inside a column.
#
# `RUBY_SHARE` is the one correction the measurement forced. Furigana sits
# beside the kanji it reads for at about 40% the size, so its nearest
# neighbour is that kanji and the step points SIDEWAYS -- seven of 34 points
# in one ordinary balloon came back at 165-180 degrees for exactly this
# reason. Dropping blobs under half the median area removes all seven.
ANGLE_MIN_AREA = 50      # a mask blob smaller than this is a speck
ANGLE_MIN_PTS = 4        # ...and fewer points than this has no direction
RUBY_SHARE = 0.5         # a blob under this share of the median is furigana
ANGLE_SPLIT = 30.0       # two runs this far apart are two pieces of writing
ANGLE_MIN_RUN = 3        # ...and a run needs this many points to be one
# ...AND WRITING SET SQUARE TO THE PAGE IS NEVER SPLIT.
#
# lee: *"teh agnle thing showu not work at 90, 0, 180, 270 +-5 degrees also
# it shou try to get teh angle of teh whole text block not sections of it"*.
#
# This is what the first five estimators were missing, and it is not a
# tolerance -- it is the whole rule. A block of vertical Japanese has TWO
# directions in it: down each column at 90, and across between columns at 0.
# Every estimator found both, called one of them "the run", and cut the block
# apart at the other. That is why seventeen ordinary balloons split.
#
# Both of those are AXIS-ALIGNED. So nothing square to the page is ever a
# second run, whichever of the two directions a point happens to step in, and
# the only thing that can be one is writing genuinely set at an angle --
# 悪女見習いさん at 135, a diagonal shout, a name laid up a sword. One rule
# instead of a threshold nobody could place.
AXIS_TOL = 5.0


def glyph_points(tmask, box, min_area=ANGLE_MIN_AREA, ruby=RUBY_SHARE):
    """A point at every character in the box, furigana left out."""
    if tmask is None:
        return np.zeros((0, 2))
    x0, y0, x1, y1 = [int(v) for v in box]
    H, W = tmask.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((0, 2))
    m = (tmask[y0:y1, x0:x1] > 0).astype(np.uint8)
    if not m.any():
        return np.zeros((0, 2))
    n, _lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    area = np.array([st[i, cv2.CC_STAT_AREA] for i in range(1, n)])
    pts = np.array([cen[i] for i in range(1, n)]).reshape(-1, 2)
    if not len(pts):
        return pts
    keep = area >= min_area
    if int(keep.sum()) > 4 and ruby:
        keep &= area >= ruby * np.median(area[keep])
    return pts[keep] + (x0, y0)


def _steps(pts, k=3):
    """Which way the writing runs AT each point, in degrees.

    Not the step to the single nearest neighbour, which was the first version
    and which cut real balloons in half. A block of vertical type is a GRID:
    the character below is one spacing away and the character in the next
    column is one spacing away too, so the nearest neighbour is sometimes
    diagonal and the step comes back at 135 degrees in the middle of perfectly
    ordinary type. Fifteen balloons on the chapter were split by exactly that.

    So the direction is fitted over each point and its `k` nearest
    neighbours -- a short local line rather than a single hop. A column of
    type gives the column's direction whichever neighbours are picked up,
    because they are all in the column; a scrawl gives the scrawl's.
    """
    out = []
    n = len(pts)
    for i, a in enumerate(pts):
        d = np.linalg.norm(pts - a, axis=1)
        near = np.argsort(d)[:min(k + 1, n)]
        q = pts[near] - pts[near].mean(0)
        if len(q) < 2:
            out.append(0.0)
            continue
        _u, _s, vt = np.linalg.svd(q, full_matrices=False)
        out.append(np.degrees(np.arctan2(vt[0][1], vt[0][0])) % 180.0)
    return np.array(out)


def _off_axis(deg):
    """How far a direction is from the nearest page axis, 0-45 degrees.

    0, 90, 180 and 270 all fold to zero: a column running down and a column
    running up are the same column, and the page has no preferred end.
    """
    return np.abs(((np.asarray(deg, float) + 45.0) % 90.0) - 45.0)


def _apart(a, b):
    """How far two directions are apart, 0-90, wrapping at 180."""
    return abs(((a - b + 90.0) % 180.0) - 90.0)


def run_angle(tmask, box, least=ANGLE_MIN_PTS):
    """Which way the writing in this box runs, in degrees, or None.

    None when there are too few characters to say -- a two-character aside, a
    `!?` -- and a box that cannot answer is never refused anything on it.
    """
    pts = glyph_points(tmask, box)
    if len(pts) < least:
        return None
    st = _steps(pts)
    # The mode rather than the mean: a mean of 5 and 175 degrees is 90, which
    # is neither of them. Widest 30-degree window wins.
    best, hits = None, -1
    for c in st:
        n = int((_apart(st, c) <= 15.0).sum())
        if n > hits:
            best, hits = float(c), n
    return best


def split_by_angle(tmask, box, apart=ANGLE_SPLIT, least=ANGLE_MIN_RUN,
                   pad=2):
    """One box holding two runs of writing becomes two boxes.

    lee: *"can you use ctd to get the angle of teh text to detemin if a new
    box need to be made?"* -- and the box that forced it, 004's
    悪女見習いさん, hand-lettered diagonally along the bottom of a balloon and
    handed back by DBNet fused to the column of type inside it. No rule about
    which boxes may JOIN can split a box that was never two; this is the one
    that can.

    Every glyph gets a point and a direction (see `run_angle`). The points
    whose direction is more than `apart` from the dominant one are a second
    run, and if there are `least` of them they get their own box.

    ## IT DOES NOT WORK, AND THE REASON IS ABOUT JAPANESE RATHER THAN CODE

    Measured over the chapter, this splits **seventeen boxes and every one of
    them is an ordinary balloon**: 007's なっなんでもありません！, 010's
    大丈夫 いずれ綺麗に戻りますよ, 019's 早速だがこの傷を治してもらう. It does
    not split 004's 悪女見習いさん, which is the box it was written for.

    **A block of vertical Japanese has two directions in it.** Down each
    column, and across between columns -- and the spacing is nearly the same
    both ways, because that is what makes it read as a block. Whichever of
    the two the estimator calls "the run", the other one is thirty degrees
    away and looks like a second piece of writing.

    Five estimators were tried and all five break here:

        per-glyph minAreaRect     a Japanese glyph is square; a third of a
                                  clean balloon reads 18-45 degrees
        elongated glyphs only     removes the noise and the signal together;
                                  five blobs left in a box
        one line through all      a block is a grid, not a line: 34px spread
        nearest-neighbour step    hops between columns, 135 degrees mid-block
        local fit over k=3        same, smoothed, still seventeen splits

    What the angle IS good for is comparing two boxes that are already
    separate -- median 0.0 for set type against 7-15 for hand-set type over
    three pages. `run_angle` is kept public for that.

    And the box it was built for could never have been fixed here anyway:
    DBNet does not see 悪女見習いさん as text in either head, so it arrives
    fused, and CTD's mask has no blobs for it inside that rectangle either.
    """
    pts = glyph_points(tmask, box)
    if len(pts) < least * 2:
        return [box]
    st = _steps(pts)
    # Square to the page is never a second run -- see `AXIS_TOL`. Both of a
    # block's own directions live here, so the whole block is one piece
    # however its points happen to step.
    off = _off_axis(st) > AXIS_TOL
    if int(off.sum()) < least or int((~off).sum()) < least:
        return [box]
    out = []
    for sel in (~off, off):
        q = pts[sel]
        out.append((int(q[:, 0].min()) - pad, int(q[:, 1].min()) - pad,
                    int(q[:, 0].max()) + pad, int(q[:, 1].max()) + pad))
    # ...unless the two land on top of each other, which means the points
    # interleave and this was one piece of writing with noisy steps in it.
    if _share(out[0], out[1]) > 0.5 or _share(out[1], out[0]) > 0.5:
        return [box]
    return out


def _glyph_tilt(tmask, box, min_area=TILT_MIN_AREA,
                least=TILT_MIN_GLYPHS):
    """How far off the page axes this box's characters are set, in degrees.

    None when the box holds too few characters to say. See `TILT_TOL`.
    """
    if tmask is None:
        return None
    x0, y0, x1, y1 = [int(v) for v in box]
    H, W = tmask.shape[:2]
    m = (tmask[max(0, y0):min(H, y1), max(0, x0):min(W, x1)] > 0)
    if m.sum() < 50:
        return None
    n, lab, st, _c = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
    tilts = []
    for i in range(1, n):
        if int(st[i, cv2.CC_STAT_AREA]) < min_area:
            continue
        ys, xs = np.nonzero(lab == i)
        if xs.size < 20:
            continue
        a = cv2.minAreaRect(np.stack([xs, ys], 1).astype(np.float32))[2] % 90
        tilts.append(min(a, 90.0 - a))
    if len(tilts) < least:
        return None
    return float(np.median(tilts))


def _runs_across(b, ratio=1.4):
    """Is this box a horizontal run rather than a vertical column?

    Square-ish boxes -- one or two characters, a `!?`, a piece of ruby --
    answer False and join columns, which is what they always are in this
    chapter. Only a box clearly wider than it is tall is a run.
    """
    w, h = b[2] - b[0], b[3] - b[1]
    return w >= ratio * h


def _side_by_side(a, b):
    """Two columns beside each other, rather than one under the other."""
    over_y = min(a[3], b[3]) - max(a[1], b[1])
    over_x = min(a[2], b[2]) - max(a[0], b[0])
    if over_y <= 0 or over_x > over_y:
        return False
    ha, hb = a[3] - a[1], b[3] - b[1]
    wa, wb = a[2] - a[0], b[2] - b[0]
    return ha >= 1.4 * wa and hb >= 1.4 * wb


def _tops_agree(a, b, tol=TOP_TOL):
    """Do these two columns start at the same height?

    Only asked of boxes that sit SIDE BY SIDE. Two columns stacked one above
    the other are a different arrangement -- a wide horizontal aside, or one
    line under another -- and the top of the lower one is meant to be lower.
    """
    if not _side_by_side(a, b):
        return True
    return abs(a[1] - b[1]) <= tol * max(a[3] - a[1], b[3] - b[1])


def _pool(boxes, nx, ny, limit, tops=False, tol=TOP_TOL,
          tmask=None):
    from . import craft as _craft
    out = []
    if not boxes:
        return out
    groups = (_split_by_top(boxes, nx, ny, tol, tmask) if tops
              else _craft.group(boxes, near_x=nx, near_y=ny))
    for g in groups:
        box = g["box"]
        if (box[2] - box[0]) * (box[3] - box[1]) <= limit:
            out.append(box)
            continue
        # Same trade as `craft._under_cap`: a panel-sized group gives itself
        # up and offers the pieces it was made of, because the writing under
        # it is real and dropping it silently is how a sound effect goes
        # missing.
        for b in (g.get("pieces") or []):
            if b != box and (b[2] - b[0]) * (b[3] - b[1]) <= limit:
                out.append(b)
    return out


def _split_by_top(boxes, nx, ny, tol, tmask=None):
    """`craft.group`'s reach, with the top test as a second condition.

    Written as its own union-find rather than by post-splitting what
    `reach_groups` returns, because a group is transitive and the top test is
    not: A joins B and B joins C does not mean A may join C, and cutting a
    finished group in two has no way to know which pair to cut.
    """
    n = len(boxes)
    par = list(range(n))
    # The span of tops inside each group, and the tallest column in it. A
    # join is refused when the MERGED span would break the tolerance, which
    # is the guard the pairwise test needs and did not have.
    span = [[b[1], b[1], b[3] - b[1]] for b in boxes]
    tilt = ([_glyph_tilt(tmask, b) for b in boxes] if TILT_TOL
            else [None] * n)

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            a, b = boxes[i], boxes[j]
            gx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
            gy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
            sz = min(max(a[2] - a[0], a[3] - a[1]),
                     max(b[2] - b[0], b[3] - b[1]))
            if gx > nx * sz or gy > ny * sz:
                continue
            # ...AND THE TOP TEST IS FOR EVERY BOX IN THIS POOL.
            #
            # lee: *"the height thing should only be for bubble text"*, then
            # *"also add the height rule to outside text"*.
            #
            # Which is the right place to land, and the pools are already the
            # line. This one holds writing the TYPE detector found -- dialogue
            # and hand-set type both, and both are set in columns that start
            # at a top edge. The sound effects are in the other pool and never
            # come through here, so a painted effect whose strokes scatter
            # down the artwork is never measured against a rule about
            # compositors.
            #
            # An `exempt` list stood here for one turn -- boxes the
            # sound-effect model also claimed skipped the test -- and it is
            # gone. It answered the narrower question lee asked first, and
            # once outside text wants the rule too there is nothing left for
            # it to exempt.
            # A COLUMN AND A LINE ARE NOT THE SAME WRITING.
            #
            # lee: *"2 text boxes being merge as one even thou one is and
            # outside text and one is a bubble etxt"* -- 004's 悪女見習いさん,
            # hand-lettered diagonally along the bottom of a balloon, folded
            # into the あんたは『このくらい当然です』 set inside it.
            #
            # The top test could not refuse it, because a diagonal scrawl is
            # not a column and the test lets anything that is not a column
            # through. But Japanese is set one way or the other, and a block
            # is all of one: a tall column of type and a wide run of
            # type beside it are two things whatever the gap between
            # them says.
            if _runs_across(a) != _runs_across(b):
                continue
            # ...and the angle the characters are set at. See `TILT_TOL`.
            if TILT_TOL and tilt[i] is not None and tilt[j] is not None \
                    and abs(tilt[i] - tilt[j]) > TILT_TOL:
                continue
            if not _tops_agree(a, b, tol):
                continue
            ra, rb = find(i), find(j)
            if ra == rb:
                continue
            # ...AND THE TOP TEST IS NOT TRANSITIVE.
            #
            # lee: *"merged 2 outside text as one even thoght they are far
            # apart and not on the samoe height"*, and *"2 text boxes being
            # merge as one even thou one is and outside text and one is a
            # bubble etxt"*.
            #
            # Both are the same defect and the docstring below named it
            # before the code guarded it: A may join B and B may join C
            # without A being allowed to join C. Each pair on 021 differed by
            # a little and the chain walked せっかく、あの王宮を down to
            # どうせ妄想するなら, which start a third of a panel apart.
            #
            # So the test is asked of the GROUP. Joining two roots is allowed
            # only when every top in the result fits inside one tolerance of
            # the tallest column in it -- which is what "one block of writing
            # starts at one height" actually says.
            lo = min(span[ra][0], span[rb][0])
            hi = max(span[ra][1], span[rb][1])
            tall = max(span[ra][2], span[rb][2])
            if _side_by_side(a, b) and hi - lo > tol * tall:
                continue
            par[ra] = rb
            span[rb] = [lo, hi, tall]

    made: dict = {}
    for i in range(n):
        made.setdefault(find(i), []).append(boxes[i])
    return [{"box": [min(q[0] for q in mine), min(q[1] for q in mine),
                     max(q[2] for q in mine), max(q[3] for q in mine)],
             "pieces": mine} for mine in made.values()]


def grouped(img: np.ndarray, db_ckpt: str, coo_ckpt: str,
            text_x: float = TEXT_X, text_y: float = TEXT_Y,
            sfx_x: float = SFX_X, sfx_y: float = SFX_Y,
            both_ways: bool = True, want_sfx: bool = True,
            same: float = SAME, cap: float = PAGE_CAP, tmask=None,
            split_angle: bool = False,
            overlap: float = OVERLAP, inside: float = INSIDE_SFX,
            bigger: float = BIGGER) -> list:
    """`[(box, "text" | "outside" | "sfx"), ...]`.

    Grouped inside each pool and never across it -- lee: *"sfx and outide ext
    shodu not be welded and bubble text shoud only weled to text very close to
    them"* -- then labelled by which pools agree, then deduplicated where the
    two describe one thing.
    """
    from . import dbtext, onomatopoeia

    H, W = img.shape[:2]
    limit = cap * W * H
    raw_sfx = (onomatopoeia.pieces(img, coo_ckpt)
               if (coo_ckpt and want_sfx) else [])
    text = _pool(dbtext.pieces(img, db_ckpt, both_ways=both_ways)
                 if db_ckpt else [], text_x, text_y, limit, tops=True,
                 tmask=tmask)
    sfx = _pool(raw_sfx, sfx_x, sfx_y, limit)

    # ...AND A BOX HOLDING TWO RUNS BECOMES TWO BOXES -- IF ASKED.
    #
    # Built, measured, and OFF, because a block of vertical Japanese has two
    # directions in it by construction and no estimator can be told which one
    # is "the" run. See `split_by_angle`.
    if split_angle:
        text = [q for box in text for q in split_by_angle(tmask, box)]

    out = []
    for box in text:
        area = max(1, (box[2] - box[0]) * (box[3] - box[1]))
        claimed = any(_share(box, c) > overlap for c in raw_sfx)
        swallowed = any(_share(box, g) > inside
                        and (g[2] - g[0]) * (g[3] - g[1]) >= bigger * area
                        for g in sfx)
        out.append((box, "outside" if (claimed and not swallowed) else "text"))
    out += [(box, "sfx") for box in sfx]

    # ...and where two pools describe one piece of writing, keep one box.
    # Biggest first, so a whole effect outranks a fragment of itself, and
    # `outside` before `sfx` at equal size, because the label that gets a box
    # translated is the one to be wrong towards.
    order = {"outside": 0, "text": 1, "sfx": 2}
    out.sort(key=lambda q: (-(q[0][2] - q[0][0]) * (q[0][3] - q[0][1]),
                            order[q[1]]))
    kept = []
    for box, name in out:
        if any(_share(box, o) > same for o, _n in kept):
            continue
        kept.append((box, name))
    # ...and last, every box reaches for the writing beside it that nobody
    # else has claimed. Done here, once the whole page's boxes exist, because
    # "nobody else has claimed it" is a question about all of them.
    return grow_to_nearby_text(tmask, kept)


def grow_to_nearby_text(tmask, boxes, near=GROW_NEAR, rounds=GROW_ROUNDS,
                        blob=GROW_BLOB):
    """Grow every box onto the writing beside it that nobody else owns.

    `boxes` is `[(box, name), ...]` as `grouped` returns it. See `GROW_NEAR`
    for the three rules; this returns the same list with the rectangles
    widened.
    """
    if tmask is None or not boxes:
        return boxes
    m = (tmask > 0).astype(np.uint8)
    if not m.any():
        return boxes
    n, _lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    keep = [i for i in range(1, n) if int(st[i, cv2.CC_STAT_AREA]) >= blob]
    if not keep:
        return boxes
    rect = np.array([[st[i, cv2.CC_STAT_LEFT], st[i, cv2.CC_STAT_TOP],
                      st[i, cv2.CC_STAT_LEFT] + st[i, cv2.CC_STAT_WIDTH],
                      st[i, cv2.CC_STAT_TOP] + st[i, cv2.CC_STAT_HEIGHT]]
                     for i in keep], float)
    mid = np.array([cen[i] for i in keep], float)
    size = np.maximum(rect[:, 2] - rect[:, 0], rect[:, 3] - rect[:, 1])
    grown = [list(b) for b, _k in boxes]

    def owner_of():
        """Which box each blob's centre falls in, or -1. Recomputed every
        round, because a box that just grew may now own a blob."""
        own = np.full(len(mid), -1)
        for bi, b in enumerate(grown):
            inside = ((mid[:, 0] >= b[0]) & (mid[:, 0] <= b[2]) &
                      (mid[:, 1] >= b[1]) & (mid[:, 1] <= b[3]))
            own[inside & (own < 0)] = bi
        return own

    for _round in range(rounds):
        own = owner_of()
        moved = False
        for bi, b in enumerate(grown):
            mine = own == bi
            if not mine.any():
                continue
            reach = near * float(np.median(size[mine]))
            # ...distance from the blob to the RECTANGLE, not to its centre:
            # a tall column beside a short one is one character away along
            # its whole length.
            dx = np.maximum(np.maximum(b[0] - rect[:, 2], rect[:, 0] - b[2]),
                            0.0)
            dy = np.maximum(np.maximum(b[1] - rect[:, 3], rect[:, 1] - b[3]),
                            0.0)
            take = (own < 0) & (np.hypot(dx, dy) <= reach)
            if not take.any():
                continue
            q = rect[take]
            b[0] = min(b[0], int(q[:, 0].min()))
            b[1] = min(b[1], int(q[:, 1].min()))
            b[2] = max(b[2], int(q[:, 2].max()))
            b[3] = max(b[3], int(q[:, 3].max()))
            own[take] = bi
            moved = True
        if not moved:
            break
    return [(tuple(g), name) for g, (_b, name) in zip(grown, boxes)]


def _grow_to_the_glyphs(tmask, box, touch=GROW_TOUCH, cap=GROW_CAP):
    """Widen a box until it holds every glyph it was cutting through.

    Only ever outward, and only to blobs the box already holds a fifth of --
    so this cannot walk across a page one letter at a time. See `GROW_TOUCH`.
    """
    x0, y0, x1, y1 = box
    H, W = tmask.shape[:2]
    lo_x = max(0, x0 - int(cap * (x1 - x0)))
    lo_y = max(0, y0 - int(cap * (y1 - y0)))
    hi_x = min(W, x1 + int(cap * (x1 - x0)) + 1)
    hi_y = min(H, y1 + int(cap * (y1 - y0)) + 1)
    win = (tmask[lo_y:hi_y, lo_x:hi_x] > 0).astype(np.uint8)
    if not win.any():
        return box
    n, lab, st, _c = cv2.connectedComponentsWithStats(win, 8)
    inside = np.zeros(win.shape, bool)
    inside[y0 - lo_y:y1 - lo_y + 1, x0 - lo_x:x1 - lo_x + 1] = True
    held = np.bincount(lab[inside].ravel(), minlength=n)
    for i in range(1, n):
        area = int(st[i, cv2.CC_STAT_AREA])
        if not area or held[i] < touch * area:
            continue
        bx = lo_x + int(st[i, cv2.CC_STAT_LEFT])
        by = lo_y + int(st[i, cv2.CC_STAT_TOP])
        x0 = min(x0, bx)
        y0 = min(y0, by)
        x1 = max(x1, bx + int(st[i, cv2.CC_STAT_WIDTH]) - 1)
        y1 = max(y1, by + int(st[i, cv2.CC_STAT_HEIGHT]) - 1)
    return (max(0, x0), max(0, y0), min(W - 1, x1), min(H - 1, y1))


def regions_from(img: np.ndarray, tmask: np.ndarray, boxes: list,
                 classify: bool = True) -> list:
    """Boxes into regions, with the ink inside each one as its mask.

    The recipe is the block loop's, deliberately unchanged: the page mask
    inside the rectangle, and where the mask found nothing, plain dark ink.
    A box that holds neither is not writing and is dropped.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    H, W = gray.shape[:2]
    out = []
    for n, (box, name) in enumerate(boxes):
        pad = int(round(PAD_SHARE * min(int(box[2]) - int(box[0]),
                                        int(box[3]) - int(box[1]))))
        pad = max(PAD_MIN, min(PAD_MAX, pad))
        x0 = max(0, int(box[0]) - pad)
        y0 = max(0, int(box[1]) - pad)
        x1 = min(W - 1, int(box[2]) + pad)
        y1 = min(H - 1, int(box[3]) + pad)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        # ...but NOT for a sound effect. lee: *"teh sfx boxes grow too much
        # past the text onto the art"*. The growth follows mask blobs, and a
        # painted effect is drawn INTO the picture -- its strokes touch the
        # hair and the hand and the speed lines it is laid over, so the blob
        # it belongs to is half a panel. A clipped letter of set type is a
        # letter; a clipped brush stroke is the drawing.
        if name != "sfx":
            x0, y0, x1, y1 = _grow_to_the_glyphs(tmask, (x0, y0, x1, y1))
        sel = np.zeros((H, W), bool)
        sel[y0:y1 + 1, x0:x1 + 1] = True
        text = (tmask > 0) & sel
        if int(text.sum()) < MIN_INK:
            text = (gray <= INK) & sel
        if int(text.sum()) < MIN_INK:
            continue
        bb = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        # WHAT A BOX IS, ASKED OF THE BALLOON RATHER THAN OF THE PAPER.
        #
        # `_classify_kind` is not called here, and lee found the reason before
        # I did: *"if you\'d rather those read as plain bubbles"* -- balloons
        # of ordinary dialogue were coming back `narration`. It asks the
        # caption question first, `_straight_edges >= RULE_SIDES`, and a
        # column of vertical Japanese type HAS straight edges: the column
        # beside it is a ruled line of ink two characters away. On a webtoon
        # that never fires, because Korean runs along a line and a block of it
        # is a ragged rectangle; a manga balloon is three or four hard
        # verticals.
        #
        # It was also the wrong question to be asking. `_classify_kind` reads
        # the paper because in `detect_comictext` there is nothing better to
        # read -- but this route runs `attach_balloons` a few lines below, and
        # that FITS the balloon. So the label is settled there, off what was
        # actually found, and everything starts as `bubble` here.
        kind = "sfx" if name == "sfx" else (
            "freefloat" if name == "outside" else "bubble")
        r = TextRegion(id=n, bbox=bb,
                       text_mask=(text.astype(np.uint8) * 255),
                       bubble_mask=None, bubble_bbox=bb, kind=kind,
                       src_vertical=(y1 - y0) > (x1 - x0) * 1.15)
        r.confidence = 1.0
        out.append(r)
    return out


def label_from_balloon(kind, fitted, wall, enclosed) -> str:
    """What a box is, once the balloon search has answered about it.

    `wall` and `enclosed` are called only if they are needed, because each is
    a Canny pass round the rectangle and the first two answers settle most
    boxes without them.

    Four rules, and the order is the whole content:

      1. **A fitted balloon is dialogue, whoever found the writing.** This is
         what was missing and what lee was looking at: a box DB++/COO had
         claimed never reached this question, so writing set in a display face
         inside a balloon came back `sfx` with no way back.
      2. **A sound effect with no fitted balloon is left alone.** Not
         promoted on the weaker evidence -- a wall that closes roundish is
         ink that happens to surround something, and paint laid over speed
         lines has that by construction -- and not demoted either, because the
         only model here trained on effects has said what it is.
      3. **Otherwise a drawn line round the writing makes it dialogue**, at
         either strength. lee's own rule from the manhwa.
      4. **And writing with nothing round it is outside text.**
    """
    from .. import kinds as _kinds
    if fitted:
        return "bubble"
    if _kinds.family_of(kind) == "sfx":
        return "sfx"
    if wall() or enclosed():
        return "bubble"
    return "freefloat"


def detect_ctd_sfx(page: Page, ctd_weights: str, coo_ckpt: str,
                   classify: bool = True, want_sfx: bool = True,
                   sfx_x: float = SFX_X, sfx_y: float = SFX_Y,
                   cap: float = PAGE_CAP, same: float = SAME,
                   glyphs: int = SFX_GLYPHS, split_texts: bool = SPLIT_TEXTS,
                   split_sfx: bool = SPLIT_SFX, **tuning) -> list:
    """comic-text-detector finds it, the specialist says which of it is paint.

    lee, arriving at this after a day of everything else: *"have ctd find
    everything first and have coo run second whatever coo finds shoud be sfx
    and everythig elese ctd finds shoudd be outide text or bubble text and do
    the find bubbe thing for bubble text"*.

    Four sentences, four steps, and each of them is one thing asked of the
    model that is best at it:

      1. **comic-text-detector finds everything.** It is 100% on the dialogue
         of this chapter and it produces the `seg` mask Clean paints with.
         Nothing it finds is thrown away.
      2. **DB++/COO says what is paint.** It is the only model here trained
         on sound effects. A box it claims is `sfx`; a box it says nothing
         about is not, whatever comic-text-detector guessed.
      3. **Everything else is writing**, and the only question left is
         whether it is in a balloon.
      4. **A balloon is looked for**, and that is what decides bubble against
         outside text -- not the brightness of the margin.

    Why the shape matters, measured over 23 pages. comic-text-detector alone
    is 5 missed and 13 junk, and **twelve of the thirteen junk boxes are its
    `sfx` family**: a hand, a face, two eyes, a fence rail, flower marks. But
    two of the boxes in that family are real WRITING it mislabelled -- 001's
    credits strip and 002's hand-lettered こういう情報は規制されません -- so
    dropping the family wholesale lost those with the junk. Letting COO be
    the one who says "paint" keeps them, as outside text, which is what they
    are.

    ## ...AND THE ONE PLACE A BOX IS STILL DROPPED

    lee: *"keep a CTD sfx box only when COO is silent and the box passes the
    balloon test or has real glyph structure. I'd want to measure it rather
    than guess"*, and after seeing what it does: *"this + this rule (now)"*.

    Measured, and one half of his sentence works. See `SFX_GLYPHS` for the
    sixteen boxes and the four things tried on them; this is what it does to
    the chapter:

        route                                   missed   junk   s/page
        comic-text-detector alone                    5     13     2.94
        CTD finds all + COO labels                   4     15     8.01
        ...with the five-body rule on  <-- this       6      4     7.71
        CTD drops its own sfx + COO replaces         9      4     7.60

    **Eleven of the fifteen junk boxes go, for two boxes of recall** -- and the
    four that are left are exactly the four the wholesale drop leaves, at three
    fewer misses than it costs. The two lost are 013's white scribble and 014's
    zigzag, both real sound effects drawn as one stroke, which is the shape
    nothing here can tell from a hand. The third box the rule drops, 007's
    せっ, costs nothing: the writing it sat on is inside another box already.

    The rule itself is free -- a connected-components pass over a mask that is
    already computed -- and the s/page column is run-to-run spread rather than
    anything the rule does.

    The balloon arm of lee's sentence was measured with it and is off: it
    changes no miss and adds one junk box back (002's fence rail, which is
    framed by drawn lines and reads as walled). `SFX_KEEP_WALLED`.
    """
    from . import balloon as B
    from . import comictext as CT
    from . import onomatopoeia
    from .. import kinds as _kinds

    img = page.image
    if img is not None and img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 1 -- everything comic-text-detector finds, nothing dropped.
    found = CT.detect_comictext(page, ctd_weights, classify=classify,
                                want_sfx=False, **tuning)
    if not (coo_ckpt and want_sfx):
        for n, r in enumerate(found):
            r.id = n
        return found

    # 2 -- and the specialist, grouped in its own pool.
    H, W = img.shape[:2]
    raw = onomatopoeia.pieces(img, coo_ckpt)
    groups = _pool(raw, sfx_x, sfx_y, cap * W * H)

    box_of = [(int(r.bbox[0]), int(r.bbox[1]),
               int(r.bbox[0]) + int(r.bbox[2]),
               int(r.bbox[1]) + int(r.bbox[3])) for r in found]

    # ...AND A BOX NOBODY BUT comic-text-detector BELIEVES IN HAS TO SHOW ITS
    # LETTERS. See `SFX_GLYPHS` for the sixteen boxes this is measured over
    # and for the three measurements that could not do it.
    #
    # `box_of` is NOT rebuilt from what survives, and does not need to be: a
    # box dropped here is one no COO group overlaps by a single pixel, so it
    # can never have been the box a group was found to be inside. The `fresh`
    # test below reads the same list either way.
    tmask = None
    if glyphs:
        tmask = getattr(page, "seg_mask", None)
        if tmask is None:
            tmask = CT.page_text_mask(img, ctd_weights,
                                      tuning.get("mask_thresh")
                                      or CT.SEG_KEEP)
    kept, apart = [], []
    for r, b in zip(found, box_of):
        claimed = any(_share(b, g) > 0.0 or _share(g, b) > 0.0
                      for g in groups)
        if claimed:
            # ...and if the specialist saw more than one effect in there, the
            # box is those effects rather than the rectangle round them all.
            # See `SPLIT_SFX`.
            bits = ([p for p in raw if _share(p, b) > SFX_PIECE_IN]
                    if split_sfx else [])
            if len(bits) > 1:
                apart += [(tuple(int(v) for v in p), "sfx") for p in bits]
                continue
            r.kind = "sfx"
            kept.append(r)
            continue
        if glyphs and _kinds.family_of(r.kind) == "sfx" \
                and glyph_bodies(tmask, b) < glyphs \
                and not (SFX_KEEP_WALLED
                         and B._round_wall_around(gray, r.bbox)):
            continue
        r.kind = "bubble"
        kept.append(r)
    found = kept

    # ...and the effects the specialist found that comic-text-detector did
    # not. A COO group mostly INSIDE a CTD box is the same thing said twice
    # and lee said which wins; a group that CONTAINS one has found more of
    # the effect than CTD did -- 001's ザァァ is 332px of COO against 197 of
    # CTD -- and the symmetric test threw those away.
    fresh = [g for g in groups if not any(_share(g, b) > same
                                          for b in box_of)]
    # ...and a group that only describes a box this pass has already broken
    # into pieces is not fresh, it is the weld coming back by another door.
    fresh = [g for g in fresh
             if not any(_share(p, g) > same for p, _k in apart)]
    if fresh or apart:
        if tmask is None:
            tmask = getattr(page, "seg_mask", None)
        if tmask is None:
            tmask = CT.page_text_mask(img, ctd_weights,
                                      tuning.get("mask_thresh")
                                      or CT.SEG_KEEP)
        found = found + regions_from(img, tmask,
                                     apart + [(g, "sfx") for g in fresh],
                                     classify=False)

    # ...AND A RECTANGLE HOLDING TWO PIECES OF WRITING BECOMES TWO.
    #
    # lee: *"teh box merging shou not happen"*, over 008's ガチャ ガチャ ガチャ
    # in one 434px rectangle, 007's ギャ + ポンッ in another, and 007's
    # せっかくあの王宮を... folded together with どうせ妄想するなら....
    #
    # The weld is NOT this route's. Measured: sweeping the sound-effect pool's
    # reach from 0.30 down to 0 -- no grouping at all -- moves the widest sfx
    # box by not one pixel and the box count by one. Every one of these
    # arrives from comic-text-detector's block head as a single rectangle, so
    # no rule about which boxes may JOIN can help; the only thing that can is
    # a pass that splits a box that was never two.
    #
    # Which the app already has. `_two_texts_in` is lee's own staircase test
    # from the manhwa -- two groups of ink sharing almost none of each other's
    # rows and columns, or separated by a band of empty wider than a line --
    # and `_each_text_its_own_box` applies it until nothing splits. It is
    # asked here with `skip_sfx=False`, because a row of painted effects is
    # exactly the case lee is pointing at and the manhwa's reason for skipping
    # them does not hold on a page where COO has already said which boxes are
    # paint.
    if split_texts:
        found = CT._each_text_its_own_box(found, skip_sfx=False)

    # 3 + 4 -- of what is left, the ones with a balloon round them are
    # dialogue. `_classify_kind` is not asked: it reads the brightness of the
    # margin, and a caption plate on a pale panel answers exactly as a
    # balloon does. `attach_balloons` fits the balloon instead, and searches
    # the negative of the page as well, for the black ones.
    #
    # ...AND THE BALLOON IS ASKED ABOUT THE SOUND EFFECTS TOO.
    #
    # lee: *"the box labblig as messed up"*, over 009's また グロウさん…ね and
    # 002's 正直誇大広告だとは思うけど… -- both plainly dialogue, both inside a
    # drawn balloon, both coming back `sfx`.
    #
    # The bug was structural rather than numerical. `speech` used to be the
    # non-sfx boxes only, so a box DB++/COO had claimed never reached the
    # balloon question at all -- and COO claims writing that is set in a
    # display face inside a balloon, because a display face is what it was
    # trained on. Once the label was `sfx` nothing could take it back.
    #
    # So every box is asked, and lee's own rule from the manhwa decides it:
    # writing with somebody's drawn line round it is bubble text. That rule
    # already outranked `_classify_kind`; there is no reason a second
    # detector's guess should outrank it either.
    #
    # THE ASYMMETRY IS DELIBERATE, AND IT IS MEASURED. Overturning the only
    # model here trained on sound effects takes the STRONGEST evidence there
    # is -- `attach_balloons` having actually FITTED a balloon to the writing
    # -- and not the two weaker tests. All three were tried over the chapter
    # and the split is clean:
    #
    #     signal                        promotes                 right?
    #     a fitted balloon mask         001 よく見てください        yes
    #                                   005 ...覗けって言います?    yes
    #                                   008 どうでした?温泉...      yes
    #                                   006 きゅっ                 arguable
    #     a round wall, nothing fitted  003 あ (over speed lines)  NO
    #                                   012 っ (over screentone)   NO
    #                                   008 おっ, 014 あーもー!     arguable
    #     the gentle enclosure test     reads three of eleven artwork
    #                                   fragments as enclosed -- see SFX_GLYPHS
    #
    # A wall that closes roundish is ink that happens to surround something,
    # and a painted effect laid over speed lines or a screentone has that by
    # construction. A FITTED balloon is a shape somebody drew and the fitter
    # found the whole of. Every clear win is in the fitted column and both
    # clear losses are outside it.
    #
    # And a sound effect with no balloon is left alone rather than demoted:
    # COO said paint, and nothing here has contradicted it.
    B.attach_balloons(gray, found)
    for r in found:
        r.kind = label_from_balloon(
            r.kind, r.bubble_mask is not None,
            lambda: B._round_wall_around(gray, r.bbox),
            lambda: B._round_wall_around(gray, r.bbox, roundish=False,
                                         lo=CT.ENCLOSE_LO, hi=CT.ENCLOSE_HI,
                                         seal=CT.ENCLOSE_SEAL))

    for n, r in enumerate(found):
        r.id = n
    return found


def detect_m109(page: Page, ctd_weights: str, seg_ckpt: str, coo_ckpt: str,
                classify: bool = True, want_sfx: bool = True,
                size: int = None, sfx_x: float = SFX_X, sfx_y: float = SFX_Y,
                cap: float = PAGE_CAP, same: float = SAME,
                inside: float = IN_BALLOON, split_sfx: bool = SPLIT_SFX,
                split_texts: bool = SPLIT_TEXTS, fill_gaps: bool = FILL_GAPS,
                glyphs: int = SFX_GLYPHS, **tuning) -> list:
    """The Manga109 segmenter for the writing, COO for the paint, CTD for ink.

    lee, shown what the segmenter does on his chapter: *"ok impliment it"*.

    Three models, and each is asked the one thing it is best at:

      1. **The Manga109 segmenter finds the writing.** 129 of 130 balloons and
         **zero false boxes** over 23 pages, in 0.86 s. See `mangaseg`.
      2. **It also finds the balloons**, so bubble-vs-outside stops being a
         Canny pass over the margin and becomes a question about a shape the
         model actually segmented. 127 of them on the chapter.
      3. **DB++/COO finds the paint**, because Manga109 does not annotate
         onomatopoeia and the segmenter has never been shown one.
      4. **comic-text-detector's `seg` head is the ink**, and only that. Its
         mask fills 0.34 of a box where the segmenter's fills 0.66 -- one is
         the strokes and the other is a blob over the text area -- and
         `inpaint` paints what the mask calls writing.

    ## THE ORDER OF THE THREE ANSWERS

    A drawn balloon outranks everything, which is the rule lee has had since
    the manhwa and the one this route can finally honour properly. Then COO,
    then nothing-round-it:

        inside a balloon shape          bubble
        else claimed by COO             sfx
        else                            outside text

    Not the other way round. A sound effect painted inside a balloon is
    dialogue set in a display face far more often than it is a noise, which is
    the same trade `label_from_balloon` makes and it is made here with better
    evidence -- a segmented shape rather than a fitted ellipse.
    """
    from . import balloon as B
    from . import comictext as CT
    from . import mangaseg, onomatopoeia

    img = page.image
    if img is not None and img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = img.shape[:2]

    # comic-text-detector runs ONCE. Its `blk` and `seg` heads are one forward
    # pass, so when the margins are being filled the boxes come free with the
    # mask -- asking `page_text_mask` for the mask and `detect_comictext` for
    # the boxes ran the same net twice and cost 3.6 s of 14.8 a page.
    spare = (CT.detect_comictext(page, ctd_weights, classify=False,
                                 want_sfx=False, **tuning)
             if (fill_gaps and glyphs) else [])
    tmask = getattr(page, "seg_mask", None)
    if tmask is None:
        tmask = CT.page_text_mask(
            img, ctd_weights,
            tuning.get("mask_thresh") or CT.SEG_KEEP)
    got = mangaseg.read(img, seg_ckpt, size or mangaseg.SIZE)
    text = got[mangaseg.TEXT]
    shapes = got[mangaseg.BALLOON]

    raw = (onomatopoeia.pieces(img, coo_ckpt)
           if (coo_ckpt and want_sfx) else [])
    groups = _pool(raw, sfx_x, sfx_y, cap * W * H) if raw else []

    boxes = []
    for b in text:
        if any(_share(b, q) > inside for q in shapes):
            boxes.append((tuple(b), "text"))
            continue
        if any(_share(b, g) > 0.0 or _share(g, b) > 0.0 for g in groups):
            # ...and one rectangle round three effects is three boxes. Same
            # rule and the same reason as in `detect_ctd_sfx`.
            bits = ([p for p in raw if _share(p, b) > SFX_PIECE_IN]
                    if split_sfx else [])
            if len(bits) > 1:
                boxes += [(tuple(int(v) for v in p), "sfx") for p in bits]
            else:
                boxes.append((tuple(b), "sfx"))
            continue
        boxes.append((tuple(b), "outside"))

    # ...and the paint the segmenter never had a class for.
    fresh = [g for g in groups
             if not any(_share(g, b) > same for b, _k in boxes)]
    boxes += [(tuple(int(v) for v in g), "sfx") for g in fresh]

    # ...AND THE PAGE FURNITURE, WHICH MANGA109 DOES NOT ANNOTATE EITHER.
    #
    # The segmenter's misses are not scattered, they are all in one place: the
    # margins. Measured against the 226 sites, the six it loses that the
    # current route holds are 001's credits strip, its chapter-title block,
    # its tall right-edge caption, its page-number line and 023's -- every one
    # of them OUTSIDE the panels. Manga109 annotates what is drawn in the
    # story; the strip along the bottom of the page is not that.
    #
    # comic-text-detector has no such idea and finds them all. What it also
    # finds is eleven pieces of artwork -- and `SFX_GLYPHS` is the rule that
    # already separates those two, measured: the credits strip carries 15
    # bodies of ink and 002's hand-set type 17, against a ceiling of 4 for
    # every artwork fragment. So the gap is filled by comic-text-detector,
    # gated on that same bar, and only where nobody else has already answered.
    if spare:
        for r in spare:
            b = (int(r.bbox[0]), int(r.bbox[1]),
                 int(r.bbox[0]) + int(r.bbox[2]),
                 int(r.bbox[1]) + int(r.bbox[3]))
            if any(_share(b, q) > 0.3 or _share(q, b) > 0.3
                   for q, _k in boxes):
                continue
            if glyph_bodies(tmask, b) < glyphs:
                continue
            boxes.append((b, "text" if any(_share(b, q) > inside
                                           for q in shapes) else "outside"))

    regions = regions_from(img, tmask, boxes, classify=False)
    if split_texts:
        regions = CT._each_text_its_own_box(regions, skip_sfx=False)
    regions = CT._drop_duplicates(regions)

    # The balloon SHAPE is still fitted, because Clean and Typeset read
    # `bubble_mask` -- but it no longer decides the kind, the segmenter did.
    B.attach_balloons(gray, [r for r in regions
                             if _kind_family(r.kind) != "sfx"])
    for n, r in enumerate(regions):
        r.id = n
    return regions


def _without_the_box_around_the_group(boxes, inside=None, least=None):
    """Drop every rectangle that is only a rectangle round other rectangles.

    lee, over two crops of 014's shop panel with the outer box and the inner
    ones both drawn: *"alaso removethe bigger box that are around ground like
    this"*.

    AnimeText answers twice about the same balloon -- once per line of writing
    and once round the lot -- and the outer answer is not a piece of writing,
    it is a bracket. Two boxes on one text is `_drop_duplicates`' problem and
    it keeps the better of the two; this is a different shape, one box over
    SEVERAL, and the right move is to keep the several.

    `inside` is how much of a smaller box has to lie in the bigger one before
    it counts as held by it, and `least` is how many it has to hold. Two,
    because one is the duplicate case and the pair may be two answers about
    one line -- three lines of a balloon inside one rectangle cannot be.
    """
    inside = NEST_IN if inside is None else inside
    least = NEST_LEAST if least is None else least
    out = []
    for b, name in boxes:
        held = 0
        area_b = max(1, (b[2] - b[0]) * (b[3] - b[1]))
        for q, _n in boxes:
            # No `q is not b` guard, because a box cannot be SMALLER than
            # itself and strict `<` is what carries that. Two rectangles of
            # exactly equal area are two answers about one thing, which is
            # `_drop_duplicates`' business rather than this pass's.
            area_q = max(1, (q[2] - q[0]) * (q[3] - q[1]))
            if area_q < area_b and _share(q, b) > inside:
                held += 1
        if held >= least:
            continue
        out.append((b, name))
    return out


def _mask_ink(tmask, b) -> int:
    """Seg-head pixels inside an (x0, y0, x1, y1) box."""
    x0, y0, x1, y1 = (int(v) for v in b[:4])
    return int((tmask[y0:y1, x0:x1] > 0).sum())


# lee: *"two bozes should not be covering teh same text if a bigger box
# cover it 100%-95%]"*. His number is the threshold. The RATIO cap is what
# keeps this rule off the panel-box problem: the measured dupes sit at 2.6x
# and 3.3x the smaller box (001's painted title boxed twice, 013's breath
# boxed inside its own two-line box), the 015 panel monster at 7.6x, and the
# vouched-breaths-in-a-panel case at 20x. A bigger box five times the smaller
# is not a second answer about the same paint - it is a different problem,
# and deleting the small REAL box into it would be the worst fix.
DUPE_IN = 0.95
DUPE_RATIO = 5.0


def _one_box_per_paint(found, dupe=DUPE_IN, ratio=DUPE_RATIO):
    """A box >=95% inside a similar-sized bigger box is the same paint twice.

    Runs AFTER the ink rule, so this only ever sees the pairs ink could not
    arbitrate - white-on-black paint leaves the seg head silent, and a
    COO-vouched fragment walks past the kids-union rule on its vouch. Both
    boxes here witness the SAME paint, so the vouch proves nothing and the
    bigger box, which holds all of it, is the answer.
    """
    out = []
    for b in found:
        bx0, by0, bx1, by1 = b[:4]
        ba = float(max(1, (bx1 - bx0) * (by1 - by0)))
        dead = False
        for o in found:
            if o is b:
                continue
            ox0, oy0, ox1, oy1 = o[:4]
            oa = float((ox1 - ox0) * (oy1 - oy0))
            if oa <= ba:
                continue                 # only a BIGGER box can absorb
            ix = max(0, min(bx1, ox1) - max(bx0, ox0))
            iy = max(0, min(by1, oy1) - max(by0, oy0))
            if ix * iy / ba >= dupe and oa / ba <= ratio:
                dead = True
                break
        if not dead:
            out.append(b)
    return out


def _backed_by_a_witness(found, tmask, raw, vouch=WITNESS_VOUCH):
    """Drop the boxes that are artwork: no seg ink, no specialist, no kept
    neighbour.

    lee, with crops of the dresses on 004: *"fix these ... bad bubble if
    possibel"*. See `WITNESS_VOUCH` for the twelve boxes of embroidery this
    removes, the one real label it costs, and the margins measured between
    them. The neighbour clause is what keeps 013's second breath: it fails
    both witnesses itself, but it stands on the box COO already vouched for,
    and a mark that shares its ground with real writing is writing.
    """
    keep, weak = [], []
    for b in found:
        if _mask_ink(tmask, b) >= MIN_INK:
            keep.append(b)
            continue
        area = float(max(1, (b[2] - b[0]) * (b[3] - b[1])))
        hit = 0
        for q in raw:
            ix = max(0, min(q[2], b[2]) - max(q[0], b[0]))
            iy = max(0, min(q[3], b[3]) - max(q[1], b[1]))
            hit += ix * iy
        (keep if hit / area >= vouch else weak).append(b)
    for b in weak:
        if any(_share(b, k) > 0.5 or _share(k, b) > 0.5 for k in keep):
            keep.append(b)
    return keep


def _one_answer_per_writing(found, tmask, raw=(), inside=ABSORB_IN,
                            same=SAME_INK, vouch=WITNESS_VOUCH):
    """One piece of writing gets one box; the INK says which one.

    lee, with crops of ちから boxed inside 癒やしの力: *"fix these  the
    double bubble"*. Sixteen nested pairs on his chapter, and size cannot
    resolve them - 020's tight inner box is the right one, 038's tight inner
    box is the wrong one. So the parent's seg ink is split between what its
    children hold and what only it holds: children holding nearly all of it
    (`SAME_INK`) mean the parent is padding round the same writing and the
    parent dies; children holding a fraction are furigana or a clipped kanji
    riding on the parent's writing, and the children die. Their ink is not
    lost either way - the survivor carries it, and the line splitter
    downstream still cuts a block into its lines.

    ONE EXEMPTION, found the first time this ran over the whole chapter: a
    child the sound-effect specialist vouches for is never a fragment. 015's
    breath strokes sat inside a panel-sized box the model also emitted, held
    a sliver of its ink - the rest of the panel's strokes made up the balance
    - and died as furigana. Furigana is never COO-claimed; a drawn breath is.
    The specialist's word outranks the arithmetic it was drowned out of.
    """
    boxes = list(found)
    dead = set()

    def coo_backed(bx):
        if not len(raw):
            return False
        area = float(max(1, (bx[2] - bx[0]) * (bx[3] - bx[1])))
        hit = 0
        for q in raw:
            ix = max(0, min(q[2], bx[2]) - max(q[0], bx[0]))
            iy = max(0, min(q[3], bx[3]) - max(q[1], bx[1]))
            hit += ix * iy
        return hit / area >= vouch
    order = sorted(range(len(boxes)),
                   key=lambda i: -(boxes[i][2] - boxes[i][0])
                   * (boxes[i][3] - boxes[i][1]))
    for bi in order:
        if bi in dead:
            continue
        B = boxes[bi]
        area_b = (B[2] - B[0]) * (B[3] - B[1])
        kids = [ai for ai, a in enumerate(boxes)
                if ai != bi and ai not in dead and _share(a, B) > inside
                and (a[2] - a[0]) * (a[3] - a[1]) < area_b]
        if not kids:
            continue
        u = np.zeros(tmask.shape, bool)
        for ai in kids:
            a = boxes[ai]
            u[int(a[1]):int(a[3]), int(a[0]):int(a[2])] = True
        x0, y0, x1, y1 = (int(v) for v in B[:4])
        held = int(((tmask[y0:y1, x0:x1] > 0)
                    & u[y0:y1, x0:x1]).sum())
        if held / max(1.0, float(_mask_ink(tmask, B))) >= same:
            dead.add(bi)
        else:
            dead.update(ai for ai in kids if not coo_backed(boxes[ai]))
    return [b for i, b in enumerate(boxes) if i not in dead]


def detect_animetext(page: Page, ctd_weights: str, anim_ckpt: str,
                     coo_ckpt: str = "", classify: bool = True,
                     want_sfx: bool = True, size: int = None,
                     sfx_x: float = SFX_X, sfx_y: float = SFX_Y,
                     cap: float = PAGE_CAP, split_sfx: bool = SPLIT_SFX,
                     split_texts: bool = SPLIT_TEXTS,
                     drop_nested: float = NEST_IN,
                     bubble_weights: str = "", **tuning) -> list:
    """One model finds everything; the balloon and the specialist name it.

    lee: *"impliment the animen text alone and maybe add ctd as a mask if
    needed"*.

    **AnimeText finds every box.** All 130 lines of dialogue, all 29 captions
    and 56 of 61 painted effects, with one junk rectangle on 23 pages. See
    `animetext` for the sweep and for what the eleven misses actually are.

    **comic-text-detector supplies the ink** and nothing else, because
    `inpaint` skips a region whose `text_mask is None`. That is the "if
    needed" and it is needed.

    Then two questions are asked of each box, in this order:

      1. **Is there a balloon round it?** `attach_balloons` fits one, and a
         fitted balloon means dialogue. This is lee's rule from the manhwa and
         it outranks everything else here.
      2. **Does the sound-effect specialist claim it?** Only if its weights
         are on the machine. AnimeText has ONE class, `text_block`, so
         without COO there is nothing that can tell a painted effect from a
         caption -- and lee, on that exact split: *"dont worry about teh
         outside text and sfx distention too much because even im having a
         hard time deferintating them, but we need to ghave te bubble text
         sorted out"*. So COO is optional and the bubbles are not.

    Anything left is outside text.
    """
    from . import balloon as B
    from . import comictext as CT
    from . import animetext as AT
    from . import onomatopoeia

    img = page.image
    if img is not None and img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = img.shape[:2]

    tmask = CT.page_text_mask(
        img, ctd_weights, tuning.get("mask_thresh") or CT.SEG_KEEP)
    found = AT.pieces(img, anim_ckpt, size or AT.SIZE)

    raw = (onomatopoeia.pieces(img, coo_ckpt)
           if (coo_ckpt and want_sfx) else [])
    groups = _pool(raw, sfx_x, sfx_y, cap * W * H) if raw else []

    # The two rules lee asked for by screenshot, in this order: what is not
    # writing at all goes first, so a junk box can never save a nested twin
    # by being its "witnessed neighbour", and one piece of writing then gets
    # exactly one box. See `WITNESS_VOUCH` and `SAME_INK`.
    found = _backed_by_a_witness(found, tmask, raw)
    found = _one_answer_per_writing(found, tmask, raw)
    found = _one_box_per_paint(found)

    boxes = []
    for b in found:
        b = tuple(b)
        if not any(_share(b, g) > 0.0 or _share(g, b) > 0.0 for g in groups):
            boxes.append((b, "text"))
            continue
        # ...and one rectangle round three effects is three boxes. Same rule
        # and the same reason as everywhere else in this module.
        bits = ([p for p in raw if _share(p, b) > SFX_PIECE_IN]
                if split_sfx else [])
        if len(bits) > 1:
            boxes += [(tuple(int(v) for v in p), "sfx") for p in bits]
        else:
            boxes.append((b, "sfx"))

    if drop_nested:
        boxes = _without_the_box_around_the_group(boxes, drop_nested)

    regions = regions_from(img, tmask, boxes, classify=False)
    if split_texts:
        regions = CT._each_text_its_own_box(regions, skip_sfx=False)
    regions = CT._drop_duplicates(regions)

    B.attach_balloons(gray, regions)
    # ...AND THE BALLOON MODEL FOR THE BALLOONS INK CANNOT FIT.
    #
    # lee: *"can you try to improve the animetext box clasification expesialy
    # the  freefloat and inside etxt"*. Measured over the 23-page chapter,
    # the text-family boxes the fitter left balloon-less split four and
    # twenty-two: four are REAL balloons it cannot fit - two clouds whose
    # bumpy outline the flood leaks through, two white-on-black - and
    # twenty-two are genuinely bare artwork. `name_the_balloons` only ever
    # ADDS a balloon where measurement found nothing, so it is exactly the
    # four it can reach.
    if bubble_weights:
        from . import comicbubble as _CB
        _CB.name_the_balloons(img, regions, bubble_weights)
    # THE WALL AND ENCLOSURE PROMOTIONS ARE GONE FROM THIS ROUTE, measured
    # off the same chapter: they promoted twelve boxes, and by eye at least
    # eleven of the twelve are monologue typeset straight onto hatched
    # artwork - the exact boxes lee circled. Ink texture reads as a wall too
    # often on manga to be trusted with the question; a FITTED balloon (from
    # the flood or from the model above) is somebody having actually drawn
    # one, and that is now the only way into `bubble` here.
    for r in regions:
        r.kind = label_from_balloon(
            r.kind, r.bubble_mask is not None,
            lambda: False, lambda: False)
    for n, r in enumerate(regions):
        r.id = n
    return regions


def _kind_family(kind: str) -> str:
    from .. import kinds as _kinds
    return _kinds.family_of(kind)


def why_not(ctd: str, db_ckpt: str, coo_ckpt: str) -> str:
    from . import dbtext, onomatopoeia
    if not ctd:
        return "comic-text-detector weights are needed for the clean mask"
    return dbtext.why_not(db_ckpt) or onomatopoeia.why_not(coo_ckpt)


def detect(page: Page, ctd_weights: str, db_ckpt: str, coo_ckpt: str,
           classify: bool = True, want_sfx: bool = True,
           mask_thresh: float = None, link_touching: float = None,
           stray_fill: float = None, join_over: float = None,
           split_texts: bool = False, split_angle: bool = False,
           **reach) -> list:
    """The whole route: CTD for the mask, the two specialists for the boxes."""
    from . import comictext as CT
    from . import balloon as B

    img = page.image
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    tmask = CT.page_text_mask(
        img, ctd_weights,
        CT.SEG_KEEP if mask_thresh is None else mask_thresh)
    boxes = grouped(img, db_ckpt, coo_ckpt, want_sfx=want_sfx,
                    tmask=tmask, split_angle=split_angle, **reach)
    regions = regions_from(img, tmask, boxes, classify=classify)

    # ...AND THEN THE RULES LEE ALREADY BUILT, IN THE ORDER THEY ALREADY RUN.
    #
    # lee: *"i remember i had a bunch of rule for teh bublle before do you
    # still have them?"* -- and then, shown that this route called four of
    # about fifteen, *"yes do that"*.
    #
    # These are lifted straight out of `detect_comictext`, same functions and
    # same order, rather than re-derived here. Three afternoons of measuring
    # went into them on the manhwa and every one has mutants at zero
    # survivors; the only thing that had to be measured again is the NUMBERS,
    # because they came off Korean and this is Japanese.
    #
    #   `_a_stray_mark`      one thin swash alone in a box is artwork
    #   `_join_overlapping`  two boxes on one piece of writing become one
    #   `_drop_duplicates`   IoU, and one family's box inside another's
    #   `_each_text_its_own_box`  one box holding two texts is split
    #
    # AND TWO OF THE FOUR ARE OFF, because the numbers did not transfer.
    # Measured on the Japanese chapter, each on its own:
    #
    #   stray_fill 0.115 -> 10 boxes go, and SIX of them are real: 006's
    #     しん…, 016's しー, 021's スッ and three lines of the handwritten
    #     note on 014. No bar fixes it -- the real writing fills 0.049 to
    #     0.177 of its box and the junk fills 0.054 to 0.158, and the two
    #     ranges lie on top of each other. A Japanese brush sfx is a thin
    #     stroke in a wide box, which is what the Korean rule was written to
    #     throw away.
    #
    #   join_over 0.05   -> 32 boxes fold into a bigger one and the bigger
    #     one is usually two balloons: 001's なんの力も感じねえな swallowed
    #     into グロウさん！, 004's 任せておけばいいんですよ into そんなに旦那
    #     が気になります？. Vertical balloons sit close and a 5% overlap is
    #     nothing between them. The manhwa case it was measured for -- two
    #     boxes on ONE piece of writing -- overlaps far more than that.
    #
    #   split_texts True -> changes nothing at all on the chapter.
    #
    # So `_drop_duplicates` is the one that runs, and it is the one with no
    # number in it. The other three are wired and defaulted off, so turning
    # one on is a measurement away rather than a rewrite.
    if stray_fill:
        regions = [r for r in regions
                   if not CT._a_stray_mark(gray, r.bbox, r.text_mask,
                                           stray_fill)]
    if join_over:
        regions = CT._join_overlapping(regions, join_over)
    regions = CT._drop_duplicates(regions)
    if split_texts:
        regions = CT._each_text_its_own_box(regions)

    # A balloon overrules the agreement, and nothing has to be added here to
    # make it: `attach_balloons` already runs `freefloat` through with
    # `promote=True`, and already searches the negative of the page for black
    # balloons. Anything it fits a balloon to comes back `bubble` whatever the
    # two detectors agreed about.
    #
    # ...AND A BOX WITH NO BALLOON IS NOT BUBBLE TEXT.
    #
    # lee: *"teh clasificatio need to improve a lot of outside text is
    # clasifided as bubble text"*, then *"dont worry about teh outside text
    # and sfx distention too much because even im having a hard time
    # deferintating them, but we need to ghave te bubble text sorted out"*.
    #
    # So the one thing that has to be right is the one thing that can be
    # measured outright: is there a balloon round this writing. `_classify_kind`
    # cannot answer it -- it reads the brightness of the MARGIN, and a caption
    # plate laid on a pale panel answers exactly as a balloon does, which is
    # why ローファンさんは時折王宮の動向を... came back red.
    #
    # This is lee's own rule from the manhwa, and the reason it was not here
    # already is that `loose_bubble` is None for manga: the demotion in
    # `detect_comictext` never runs on a manga page, because comic-text-
    # detector's block head was accurate enough on manga that nobody needed
    # it. These boxes do not come from the block head.
    #
    # Three ways to keep the word, and all three are somebody's drawn line
    # round the writing rather than a measurement of the paper:
    #
    #   a fitted balloon   `attach_balloons` found a run of paper round it
    #   a round wall       `balloon._round_wall_around` at its own thresholds
    #   an enclosure       the same, at the gentle ones, for a caption frame
    #                      or a plate that is not roundish
    #
    # WHERE THAT STILL LEAVES TWO BOXES WRONG, on this chapter: 009's
    # ...調子狂うぜ and 018's そろそろその価値を確かめさせろ are both white
    # typesetting inside a black balloon, which is the one shape lee's rule
    # reads backwards -- COO sees paint, DBNet's inverted pass sees type, they
    # agree, and the label says outside. Both are plainly dialogue, and the
    # balloon search does not fit either one, so neither is promoted. Two
    # boxes of the fifteen, and the other thirteen are right: the chapter
    # title, the credits line, ほか, また / グロウさん / ね, 店主, そんなので足り
    # るかよ, and five captions typeset straight onto dark panels.
    B.attach_balloons(gray, regions)
    for r in regions:
        if r.kind not in ("bubble", "narration"):
            continue
        # A fitted balloon, or a wall that closes ROUNDISH round the writing.
        # Both are somebody having drawn a balloon; the second is the case
        # the fitter misses because the balloon is far bigger than its text.
        if r.bubble_mask is not None or B._round_wall_around(gray, r.bbox):
            r.kind = "bubble"
            continue
        # ...or an enclosure at the gentle thresholds, for the balloons the
        # roundness test refuses. A SHOUT is the case that matters: 008's
        # エーダ 本当にどうしました!? is drawn as a ring of spikes, which is
        # not roundish by any measure and is unmistakably a balloon.
        #
        # This used to answer `narration` -- an enclosure that is not round is
        # a ruled plate, a sign, a title card -- and it was wrong twice over.
        # Wrong on the shouts, and wrong in principle: `project.detect` runs
        # every kind through `kinds.detected_kind`, which clamps anything
        # outside the three families back to `bubble`, because *"teh find text
        # shoud only use teh 3 defasut boxes"*. A detector can measure that
        # something is a closed shape with writing in it; it cannot measure
        # that this one is a caption and that one is a shout, and guessing
        # produced a colour the person then had to correct.
        #
        # So this route emits the three defaults and nothing else.
        if B._round_wall_around(gray, r.bbox, roundish=False,
                                lo=CT.ENCLOSE_LO, hi=CT.ENCLOSE_HI,
                                seal=CT.ENCLOSE_SEAL):
            r.kind = "bubble"
            continue
        r.kind = "freefloat"
    if link_touching:
        regions = B.link_touching_bubbles(gray, regions, link_touching)
    for n, r in enumerate(regions):
        r.id = n
    return regions
