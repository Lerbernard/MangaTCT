"""Core data structures. Every stage reads and writes these."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
from . import kinds as _kinds

# A box's kind is one of the three families, or the key of a sub-type somebody
# made under one of them - so it is a string, not a closed set. `kinds.py` is
# where a kind is turned into the family that decides how the box behaves.
RegionKind = str


def turned_box(bbox, turn: float) -> list:
    """The four corners of `bbox` turned `turn` degrees about its own centre.

    Turning a box somebody drew is stored as GEOMETRY and not as a setting off
    to one side, and that is what makes the rest of the app follow it without
    being told: `project._is_a_box` answers False for a tilted rectangle, so
    the region loads with a real placement area, and that area is what the
    cleaner erases inside and the fitter sets text into.

    Clockwise, to match `TextRegion.angle` and the sound-effect reader. Here
    with the region rather than with the project because it is read on the way
    OUT as well - the cleaner rebuilds a turned box's own outline from it, and
    the cleaner cannot import the project (the project imports the cleaner).
    """
    x, y, w, h = (float(v) for v in bbox)
    cx, cy = x + w / 2.0, y + h / 2.0
    a = math.radians(float(turn or 0.0))
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for px, py in ((x, y), (x + w, y), (x + w, y + h), (x, y + h)):
        dx, dy = px - cx, py - cy
        out.append([int(round(cx + dx * ca - dy * sa)),
                    int(round(cy + dx * sa + dy * ca))])
    return out


@dataclass
class TextRegion:
    """One piece of text on the page, tracked from detection through render."""

    id: int
    bbox: tuple[int, int, int, int]          # x, y, w, h  of the TEXT
    text_mask: Optional[np.ndarray] = None   # what we must erase
    bubble_mask: Optional[np.ndarray] = None # where we may place English
    # ...and, when this block SHARES a balloon, the part of it the fitter
    # actually gave this block. `share_masks` divides a balloon between the
    # blocks in it and can divide it differently from the detector - a balloon
    # drawn as two lobes goes lobe to a block, whatever the ink underneath
    # said - so the shape the words were fitted into is not `bubble_mask` and
    # the renderer must not clip them with `bubble_mask`. It did, and every
    # letter standing on the difference was deleted: lee's REGION came off the
    # page as 'EGION. Filled in by `typeset_page`, which always runs before
    # anything renders; never stored, like the masks above.
    share_mask: Optional[np.ndarray] = None
    bubble_bbox: Optional[tuple[int, int, int, int]] = None
    # Outline of the bubble in page coordinates. Masks are rebuilt from this on
    # demand so a whole chapter can be held in memory as geometry, not bitmaps.
    polygon: Optional[list] = None
    # A better balloon for the TYPESETTER only, written by the balloon check
    # (`balloonck`) when the saved outline runs off its balloon and the
    # model's balloon clearly holds this box alone. The fitter and everything
    # placement-side prefer it; the CLEANER never reads it - the erase masks
    # still come from `polygon`, deliberately, because every past change to
    # the cleaning mask moved something else, and lee asked for exactly this
    # scope: *"it should only help the typesetter on bubble text"*.
    fit_poly: Optional[list] = None
    kind: RegionKind = "bubble"
    panel_id: Optional[int] = None
    order: int = -1
    # Regions sharing the same positive `link` id are ONE continuous line of
    # dialogue split across bubbles. The translator is told to read them as a
    # single sentence in order; 0 means unlinked.
    link: int = 0
    # WHY they are linked, which is two different facts that used to share one
    # field. "sentence" is `translate.reads_on`: the words run on, so the halves
    # are only correct read together. "balloon" is
    # `detect.balloon.link_touching_bubbles`: the artist drew two lobes that
    # touch, which is a fact about the PICTURE and says nothing about the words
    # - a double balloon holds two sentences as often as one.
    #
    # They were both `link`, and the translation prompt reads a link as "one
    # sentence split across bubbles", so page 049's two complete sentences came
    # back welded with a comma: "His soul is completely gone, and in just a few
    # hours, he'll stop breathing altogether."
    link_kind: str = ""
    # Regions sharing the same positive `box_group` are SECTIONS of one
    # balloon. lee: "make it so that the bubbles can have 2 sections ... under
    # teh one box". A balloon can hold a sentence and a small あっ！ beneath it -
    # two things to read, two things to typeset, each in its own part of the
    # paper - but one outline, so the editor draws one box round the group
    # instead of a box each. Each section still carries its own share of the
    # balloon in `bubble_mask`, which is what the typesetter measures against.
    box_group: int = 0

    src_text: str = ""
    src_vertical: bool = True
    ocr_ok: bool = True

    # A sound effect's own axis, read off the original ink at detection time -
    # the last moment the page still carries the Japanese. `angle` is degrees
    # clockwise from straight, 0 when the reader refused to guess. `sfx_len`
    # and `sfx_wid` are the ink's footprint along and across that axis, held
    # as fractions of the box's own long and short sides so that resizing the
    # box takes the typesetting with it. Zero means nobody has measured this
    # region: everything detected before the reader existed loads that way,
    # and the box's own shape stands in.
    angle: float = 0.0
    sfx_vertical: bool = False
    sfx_len: float = 0.0
    sfx_wid: float = 0.0

    # How far somebody TURNED this box, in degrees clockwise. Its own field and
    # not `angle`, because the two say different things and a box can have
    # both: `angle` is a reading of the artwork - the axis a sound effect was
    # drawn along - while this is a decision about the box. Reading a turn out
    # of `angle` would have turned every sound effect drawn by hand, since the
    # axis reader gives each one an angle the moment it is drawn.
    #
    # Only a box somebody drew can carry one. lee: *"only teh ser shoud be
    # able to rotate them the detector boxes shoud be normal"*.
    turn: float = 0.0


    dst_text: Optional[str] = None
    dst_compact: Optional[str] = None
    speaker: Optional[str] = None
    confidence: float = 0.0

    # filled by typeset
    layout: Optional["TextLayout"] = None
    # Hand edits to the typesetting: line breaks, size, nudge. When `locked` is
    # set these win over the automatic fit, so a human correction is never
    # silently recomputed away.
    layout_override: Optional[dict] = None
    # What the ORIGINAL writing in this box was drawn with, read off the
    # artwork by `inkstyle.measure_page`: the ink colour, the colour and width
    # of any keyline round it, whether the letterform is hollow.
    #
    # A field of its own, and it had to become one. It used to be written into
    # `layout_override`, beside the hand corrections, and `render._hollow_
    # colours` already said what was wrong with that - *"that is the MEASURED
    # ink colour, not somebody's choice, and there is nothing in the record to
    # tell the two apart"*.
    #
    # What it cost: pressing Typeset means "put this page back to what the
    # fitter would do", so it empties `layout_override` - and it emptied the
    # measurement with it. Typeset always follows the read, so the first press
    # threw the answer away, every time, on every chapter ever typeset. lee,
    # looking at a sound effect that came back white-on-black where the
    # original was black with a thin white keyline: *"i feel like all the copy
    # style chnages that we worked on is not live"*. It was not.
    #
    # Now each can be treated as what it is: Typeset clears the hand
    # corrections and REFRESHES this, and a hand correction still wins over it
    # wherever both have something to say.
    layout_measured: Optional[dict] = None
    flagged: Optional[str] = None            # human-review reason
    # Leave this region's source text alone during cleaning, so an individual
    # cleaning the person does not like can be switched off.
    skip_clean: bool = False
    # Which way this box was actually cleaned - "flat fill", "neural",
    # "telea", "pattern copy" - and whether only its letter strokes went.
    #
    # The cleaner has always known this per box and thrown it away, keeping
    # only a count for the whole chapter. Several rounds of "why did THIS box
    # come out like that" were spent guessing at it: lee's report said six
    # boxes were filled flat on a page with five plain bubbles on it, and
    # there was no way to ask which the sixth was.
    clean_route: str = ""
    clean_core: bool = False

    @property
    def cx(self) -> float:
        return self.bbox[0] + self.bbox[2] / 2

    @property
    def cy(self) -> float:
        return self.bbox[1] + self.bbox[3] / 2

    @property
    def area(self) -> int:
        return self.bbox[2] * self.bbox[3]

    def place_mask(self) -> Optional[np.ndarray]:
        """Mask English text must fit inside. Bubble if we have one, else the box.

        The fallback is the BOX, not the ink standing in it. Japanese runs down
        the page in a tall narrow column, so the footprint of the writing being
        replaced is a tall narrow column with holes punched through it, and the
        fitter measures the room on every line from that shape. Typesetting
        English into it is why speech with no balloon came out at single
        figures inside a box with room for twenty.

        Sound effects are the exception and keep the ink: they are drawn along
        an axis of their own, over artwork, and the place they belong is
        exactly where the original was - not spread across a rectangle drawn
        round it. Free-floating dialogue used to be treated the same way and
        should not have been. It is ordinary speech that happens to have no
        balloon round it, so it wants to be set as a block like any other, and
        measuring it against the Japanese columns is what made lee's on-art
        lines both small and crooked: a stack of columns of unequal height has
        a different chord at every line, so the block came out as a staircase.
        A box has one chord, which is the shape a paragraph belongs in.
        """
        if self.bubble_mask is not None:
            return self.bubble_mask
        if self.text_mask is None or _kinds.family_of(self.kind) == "sfx":
            return self.text_mask
        return self.box_mask(self.text_mask.shape[:2])

    def box_mask(self, shape=None) -> Optional[np.ndarray]:
        """The region's own rectangle, as a page-sized mask.

        `place_mask` has said "bubble if we have one, else the box" since it
        was written, and it kept that promise only while some other mask was
        around to say how big the page is: with `text_mask` gone it returned
        `None` and the typesetter was handed nothing at all.

        Every region in a REOPENED chapter is in exactly that state -
        `to_dict` drops the masks, so nothing written to disk remembers a
        shape - and a block re-typeset after a reload came back with no lines
        in it. lee: *"if the typesetter can't find a box it hsoud fall back to
        using the box"*.

        With no mask to measure the page by, the array is cut off at the box's
        own far corner. Everything downstream works in page coordinates from
        (0, 0), so a shorter array holds the box in the same place a full-page
        one would; it is only missing paper nothing was going to be drawn on.

        **It is not what `place_mask` hands the CLEANER.** This is the room the
        English may use. The eraser reads `place_mask()` too, and a box-shaped
        answer there would rub out a rectangle of artwork round writing whose
        footprint nobody could find - so the fallback belongs to the fitter
        that asked for it, and stays out of the mask everything shares.
        """
        try:
            x, y, w, h = [int(v) for v in (self.bbox or (0, 0, 0, 0))]
        except (TypeError, ValueError):
            return None
        if w <= 0 or h <= 0:
            return None
        if shape is None:
            for m in (self.text_mask, self.bubble_mask, self.share_mask):
                if m is not None:
                    shape = m.shape[:2]
                    break
        if shape is None:
            shape = (max(1, y + h), max(1, x + w))
        H, W = int(shape[0]), int(shape[1])
        x, y = max(0, min(x, W - 1)), max(0, min(y, H - 1))
        w, h = max(1, min(w, W - x)), max(1, min(h, H - y))
        box = np.zeros((H, W), np.uint8)
        box[y:y + h, x:x + w] = 255
        return box

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("text_mask", "bubble_mask", "share_mask", "layout"):
            d.pop(k, None)
        if self.polygon is not None:
            d["polygon"] = [[int(a), int(b)] for a, b in self.polygon]
        d["has_bubble"] = self.bubble_mask is not None
        return d


@dataclass
class TextLayout:
    """Result of the typesetting fit search."""

    lines: list[str]
    font_size: int
    leading: float
    # top-left origin of each line, page coordinates
    line_origins: list[tuple[int, int]] = field(default_factory=list)
    used_compact: bool = False
    fit_ok: bool = True
    score: float = 0.0
    font_path: str = ""
    # Colours chosen from the background, so the live preview in the browser
    # can match what the exported page will look like.
    fg: str = "#000000"
    edge: str = "#ffffff"
    stroke: int = 1
    rotate: float = 0.0
    # The text's own box, in page coordinates: x, y, w, h. Independent of the
    # region - it can be moved, resized and rotated past the bubble edge.
    frame: tuple[int, int, int, int] | None = None
    # True when the line positions are NOT "evenly down the frame": a sound
    # effect running along its own axis, or a speech split between the two
    # lobes of a double balloon. Everything that would otherwise re-derive the
    # positions from the frame - the browser's preview, the box you type into
    # - leaves these exactly where they are.
    fixed: bool = False
    # What the fit this layout came out of was fitted FROM: a fingerprint of
    # everything on the page that decides where the lines land - the boxes, the
    # words, the shapes, the font settings, and the hand edits that steer a
    # fit. See `typeset.page_fit_key`.
    #
    # It is here so that rendering a page that has not changed can use the
    # layout it already has instead of fitting every block again. That fitting
    # is 2.6 seconds of the 3 it takes to build a finished page, and it was
    # being paid on every render, every export, and every restart.
    fit: str = ""
    # True when this block is deliberately BIGGER than the box it belongs to.
    # Outside text and sound effects are allowed to run onto the artwork
    # rather than shrink under the minimum size - lee: *"outside text and sfx
    # shoud be able to go outside teh box if the text size is bellow the
    # minimum"*. Everything that pulls a block back inside its region
    # (`pull_to_box`, `enforce_bounds`) leaves a spilling one alone, or the
    # spill is undone the moment it is made.
    spills: bool = False



@dataclass
class Page:
    image: np.ndarray
    source_path: str = ""
    panels: list[tuple[int, int, int, int]] = field(default_factory=list)
    regions: list[TextRegion] = field(default_factory=list)
    clean_plate: Optional[np.ndarray] = None
    # Who cleaned what, filled in by inpaint_page: {"flat fill": 12,
    # "neural": 6, ...}. lee kept having to guess whether the hosted model was
    # doing the hard regions or whether the local fill had quietly taken them
    # all; this is the count that answers it.
    clean_stats: dict = field(default_factory=dict)

    @property
    def h(self) -> int:
        return self.image.shape[0]

    @property
    def w(self) -> int:
        return self.image.shape[1]

    def ordered(self) -> list[TextRegion]:
        return sorted(self.regions, key=lambda r: r.order)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(
            {
                "source": self.source_path,
                "size": [self.w, self.h],
                "panels": self.panels,
                "regions": [r.to_dict() for r in self.ordered()],
            },
            indent=indent,
            ensure_ascii=False,
        )
