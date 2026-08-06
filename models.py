"""Core data structures. Every stage reads and writes these."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

import numpy as np
from . import kinds as _kinds

# A box's kind is one of the three families, or the key of a sub-type somebody
# made under one of them — so it is a string, not a closed set. `kinds.py` is
# where a kind is turned into the family that decides how the box behaves.
RegionKind = str


@dataclass
class TextRegion:
    """One piece of text on the page, tracked from detection through render."""

    id: int
    bbox: tuple[int, int, int, int]          # x, y, w, h  of the TEXT
    text_mask: Optional[np.ndarray] = None   # what we must erase
    bubble_mask: Optional[np.ndarray] = None # where we may place English
    bubble_bbox: Optional[tuple[int, int, int, int]] = None
    # Outline of the bubble in page coordinates. Masks are rebuilt from this on
    # demand so a whole chapter can be held in memory as geometry, not bitmaps.
    polygon: Optional[list] = None
    kind: RegionKind = "bubble"
    panel_id: Optional[int] = None
    order: int = -1
    # Regions sharing the same positive `link` id are ONE continuous line of
    # dialogue split across bubbles. The translator is told to read them as a
    # single sentence in order; 0 means unlinked.
    link: int = 0
    # Regions sharing the same positive `box_group` are SECTIONS of one
    # balloon. lee: "make it so that the bubbles can have 2 sections ... under
    # teh one box". A balloon can hold a sentence and a small あっ！ beneath it —
    # two things to read, two things to typeset, each in its own part of the
    # paper — but one outline, so the editor draws one box round the group
    # instead of a box each. Each section still carries its own share of the
    # balloon in `bubble_mask`, which is what the typesetter measures against.
    box_group: int = 0

    src_text: str = ""
    src_vertical: bool = True
    ocr_ok: bool = True

    # A sound effect's own axis, read off the original ink at detection time —
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
    flagged: Optional[str] = None            # human-review reason
    # Leave this region's source text alone during cleaning, so an individual
    # cleaning the person does not like can be switched off.
    skip_clean: bool = False
    # Which way this box was actually cleaned — "flat fill", "neural",
    # "telea", "pattern copy" — and whether only its letter strokes went.
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
        exactly where the original was — not spread across a rectangle drawn
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
        H, W = self.text_mask.shape[:2]
        x, y, w, h = [int(v) for v in (self.bbox or (0, 0, 0, 0))]
        x, y = max(0, min(x, W - 1)), max(0, min(y, H - 1))
        w, h = max(1, min(w, W - x)), max(1, min(h, H - y))
        box = np.zeros((H, W), np.uint8)
        box[y:y + h, x:x + w] = 255
        return box

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("text_mask", "bubble_mask", "layout"):
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
    # region — it can be moved, resized and rotated past the bubble edge.
    frame: tuple[int, int, int, int] | None = None
    # True when the line positions are NOT "evenly down the frame": a sound
    # effect running along its own axis, or a speech split between the two
    # lobes of a double balloon. Everything that would otherwise re-derive the
    # positions from the frame — the browser's preview, the box you type into
    # — leaves these exactly where they are.
    fixed: bool = False
    # True when this block is deliberately BIGGER than the box it belongs to.
    # Outside text and sound effects are allowed to run onto the artwork
    # rather than shrink under the minimum size — lee: *"outside text and sfx
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
