"""What kind of writing a box is: three families, and sub-types under them.

lee: *"revamp the box type, there need to be 3 main box type, boubble box,
outide box and sfx box, they need to have sub categories, so ttought boubles
shoud be a sub category of the the bubble type same as anfry bubbles"*.

There were six flat types - speech, open typesetting, SFX, caption, thought,
burst - sitting side by side in one menu with six unrelated colours, plus up
to ten more the person could add anywhere in the same list. Nothing said that
a thought balloon and a burst are both BALLOONS, and the colours actively said
they were not.

So: three families, and every box belongs to exactly one.

    bubble      a closed shape with a tail, whatever it is shaped like
    freefloat   dialogue lying on the artwork with nothing drawn round it
    sfx         a drawn sound

A family is a grouping and nothing else - it has no colour of its own. What a
box actually IS is a SUB-TYPE, and every family comes with one that cannot be
removed or renamed, because a box has to be something:

    bubble      Regular speech
    freefloat   Freefloat text
    sfx         Sound effect

The default sub-type's key is the family's own name, which is what every box
already stored on disk says, so nothing has to be rewritten to read it.

Ten more per family can be added, renamed and deleted (`SUBS_PER_FAMILY`), so
eleven per family at most, and every family starts with a few already made.

**Colour belongs to the sub-type, and stays inside the family.** lee: *"the
main catheory shou not have a color but the defaut shoud have the color, also
only allow color with a color family for teh 5 user craeted boxex"*. Each
family's default owns a colour; the sub-types under it can only be shades of
that same colour. So a glance at a box says which family it is in before it
says which sub-type - which is the way round that matters when you are looking
at a page rather than a menu.

**Find text only ever produces the three defaults.** A detector can measure
that something is a balloon; it cannot know that this one is a thought and
that one is angry. Anything finer is a decision, and a decision is the
person's. lee: *"teh find text shoud only use teh 3 defasut boxes"*.
"""
from __future__ import annotations

import colorsys

FAMILIES: tuple[str, ...] = ("bubble", "freefloat", "sfx")

# What the three are called where a person has to choose one.
FAMILY_LABELS = {
    # lee: *"instad of bullon it shodu be bubble text and outside text"*.
    "bubble": "Bubble text",
    "freefloat": "Freefloat text",
    "sfx": "Sound effect",
}

# ...and what each family's undeletable sub-type is called. The key of this
# sub-type IS the family name - see the module docstring.
DEFAULT_LABELS = {
    "bubble": "Regular speech",
    "freefloat": "Freefloat text",
    "sfx": "Sound effect",
}

# The family's colour, carried by its default sub-type. These are the three
# that were already in use for the three families, so a page typeset before
# this change looks the same afterwards.
FAMILY_COLOUR = {
    "bubble": "#ed4545",        # red
    "freefloat": "#2cdd60",     # green
    "sfx": "#a550e2",           # purple
}

SUBS_PER_FAMILY = 10            # ...plus the default, so eleven in a family

# How wide a family's hue is allowed to run, either side of its own colour.
#
# +/- 0.034 of a turn is about twelve degrees. The three families sit a third
# of a turn apart, so nothing here can reach anything else's territory - and
# yellow (the SELECTED box) and blue (a link) stay well clear of all three.
#
# Some hue spread is unavoidable now. lee first asked for five sub-types per
# family and then for ten, and *"mak teh colors different eniught so its
# notivcelble of the subtypes"*: ten shades of one exact hue differ only in
# how light and how grey they are, and the middle six of those are the same
# colour as far as a thin box outline on a page is concerned. Twelve degrees
# buys real separation and still reads as one family.
_HUE_SPAN = 0.034
_SAT_STEPS = (0.45, 0.62, 0.78, 0.90, 1.00)
_VAL_STEPS = (0.40, 0.54, 0.68, 0.82, 0.96, 1.10)


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v * 255))))
                                   for v in rgb)


def _hsv_of(hexstr: str):
    r, g, b = (int(hexstr[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    return colorsys.rgb_to_hsv(r, g, b)


def _far_apart(base, n: int) -> list:
    """`n` colours from the family's own patch of colour space, chosen so that
    the two closest of them - counting the family colour itself - are as far
    apart as they can be.

    Picked greedily rather than laid out on a ramp. A ramp spaces its steps
    evenly in whatever it varies, which is not the same as spacing the COLOURS
    evenly: five even steps of lightness at full saturation gave three shades
    of red nobody could tell apart and two nobody would call red. Taking the
    candidate furthest from everything chosen so far spends the whole patch
    instead of one line through it.
    """
    h0, s0, v0 = _hsv_of(base)
    cand = []
    for k in range(7):
        dh = -_HUE_SPAN + 2 * _HUE_SPAN * k / 6.0
        for sm in _SAT_STEPS:
            for vm in _VAL_STEPS:
                v = min(1.0, v0 * vm)
                if v < 0.20:
                    continue
                cand.append(colorsys.hsv_to_rgb((h0 + dh) % 1.0,
                                                min(1.0, s0 * sm), v))
    chosen = [colorsys.hsv_to_rgb(h0, s0, v0)]
    def apart(c):
        return min(sum((a - b) ** 2 for a, b in zip(c, x)) ** 0.5
                   for x in chosen)
    while len(chosen) <= n and cand:
        best = max(cand, key=apart)
        chosen.append(best)
        cand.remove(best)
    picks = chosen[1:]
    picks.sort(key=lambda c: -colorsys.rgb_to_hsv(*c)[2])   # light to dark
    return picks


_SHADE_CACHE: dict = {}


def family_shades(family: str) -> list[str]:
    """The colours a sub-type of this family may be, light to dark.

    Same family as its own colour, always - that is what makes a box say which
    of the three it is before it says which sub-type, which is the way round
    that matters when you are looking at a page rather than a menu.
    """
    if family not in _SHADE_CACHE:
        base = FAMILY_COLOUR.get(family) or FAMILY_COLOUR["bubble"]
        _SHADE_CACHE[family] = [_hex(c)
                                for c in _far_apart(base, SUBS_PER_FAMILY)]
    return list(_SHADE_CACHE[family])


def is_family(kind: str) -> bool:
    """Is this the key of a family - which is also its default sub-type?"""
    return kind in FAMILIES


# The sub-types of the project that is open.
#
# Which family a box belongs to is a question asked from places that have no
# way to reach the settings: `PageState.shown`, for one, which is a dataclass
# on a page and decides whether a hidden family's boxes count - and it is
# asked for every box on every page, constantly. Threading the settings list
# through all of it would be a lot of plumbing for a value that cannot differ:
# an editor serves ONE project (`editor.PROJECT`), and a project has one list.
#
# So the open project registers its list here when it loads, and every lookup
# that is not given one explicitly uses it. Passing `subs` still overrides it,
# which is what the tests do and what anything holding two projects at once
# would have to do.
_OPEN: list = []


def use(subs) -> None:
    """Register the open project's sub-types as the ones to look up."""
    global _OPEN
    _OPEN = [s for s in (subs or ()) if isinstance(s, dict) and s.get("key")]


def known() -> list:
    return list(_OPEN)


def _subs(subs):
    return _OPEN if subs is None else subs


def family_of(kind: str, subs=None) -> str:
    """Which family a kind belongs to.

    An unknown kind is a balloon. That is not a guess for its own sake: a kind
    that has been deleted from the settings, or that came from a project file
    written by a newer version, still has boxes on pages pointing at it, and
    those boxes have to keep drawing and keep being cleaned. Balloon is the
    family where being wrong costs least - it is the one that gets cleaned and
    typeset normally.
    """
    if kind in FAMILIES:
        return kind
    for s in _subs(subs) or ():
        if isinstance(s, dict) and s.get("key") == kind:
            f = s.get("family")
            return f if f in FAMILIES else "bubble"
    return "bubble"


def subs_of(family: str, subs=None) -> list[dict]:
    """The sub-types under one family, in the order they were added."""
    return [s for s in (_subs(subs) or ())
            if isinstance(s, dict) and s.get("key")
            and (s.get("family") if s.get("family") in FAMILIES
                 else "bubble") == family]


def kind_label(kind: str, subs=None) -> str:
    if kind in FAMILIES:
        return DEFAULT_LABELS[kind]
    for s in _subs(subs) or ():
        if isinstance(s, dict) and s.get("key") == kind and s.get("label"):
            return str(s["label"])
    return kind


def kind_colour(kind: str, subs=None) -> str:
    """The colour a box of this kind is drawn in.

    A family's default carries the family colour; anything else carries a
    shade of it. A sub-type with no colour recorded - or one carrying a colour
    from before this change, which could be any hue at all - is given the
    first shade of its own family rather than drawn in a colour that lies
    about which family it is in.
    """
    if kind in FAMILIES:
        return FAMILY_COLOUR[kind]
    for s in _subs(subs) or ():
        if isinstance(s, dict) and s.get("key") == kind:
            fam = s.get("family") if s.get("family") in FAMILIES else "bubble"
            shades = family_shades(fam)
            col = str(s.get("color") or "").lower()
            return col if col in shades else shades[0]
    return family_shades("bubble")[0]


# --------------------------------------------------------------- the detector

# What Find text is allowed to call a box. Every detector in the project
# reports one of these four names, and `narration` is a judgement rather than
# a measurement - the box is a caption, which is a decision about what the
# writing IS, not about what shape was found. It comes back as a balloon and
# the person moves it to whatever sub-type they keep captions in.
def detected_kind(kind: str) -> str:
    """Clamp whatever a detector said to one of the three defaults."""
    return kind if kind in FAMILIES else "bubble"


# ------------------------------------------------------------- the migration

# What a project starts with, per family.
#
# lee: *"add some preloaded custom bubble type ... naration type shiude be in
# both bubble and outside box as a pre loaded custum"*. These are ordinary
# sub-types - rename them, recolour them, delete the ones you never use. They
# are here because a page of manga has more than three kinds of writing on it
# and starting from three empty families means naming them all yourself before
# you can label anything.
#
# The three at the head of the balloon list - caption, thought and burst -
# were built-in types before families existed, in the flat menu beside the
# families themselves. They keep their keys, so a page already labelled with
# one keeps its label; what changes is that they can now be renamed and
# deleted like anything else, and they are the right colour for a balloon
# rather than the blue, orange and pink they used to be.
#
# NARRATION IS IN TWO FAMILIES, deliberately, and they are two different
# things. A caption in a ruled box is a balloon: a closed shape with writing
# in it, cleaned and typeset like one. Narration lying straight on the
# artwork has no shape at all, and belongs with the rest of the open
# typesetting. They are the same VOICE and a different piece of drawing, and it
# is the drawing this list is about.
# lee, with a picture of the list he wants: *"only these should be default"*.
# Four under Bubble text, three under Outside text, two under Sound effect -
# Yell, Angry and Flashback are gone. A preload is a starting point, not a
# catalogue: every one of them is a row somebody has to read past before they
# reach their own, and a shout, a yell and an angry line are one kind of
# typesetting asked for three times.
PRELOADED = {
    "bubble": (("narration", "Caption box"),
               ("thought", "Thought bubble"),
               ("shout", "Burst / shout"),
               ("whisper", "Whisper")),
    "freefloat": (("narration_free", "Narration on the art"),
                  ("aside", "Aside / mutter"),
                  ("sign", "Sign or label")),
    "sfx": (("sfx_big", "Big / impact"),
            ("sfx_small", "Small / background")),
}

PRELOAD_KEYS = tuple(k for items in PRELOADED.values() for k, _ in items)


def migrate(subs, seed: bool = False, offered=None) -> list[dict]:
    """Check a settings list, and optionally seed it with `PRELOADED`.

    Everything except the seeding is idempotent and runs on every load and
    every save: each sub-type lands in a real family, in a colour that family
    issues, and no family goes over its ten.

    Seeding is the once-per-project part, and it is separate because it has to
    be. Adding anything missing from `PRELOADED` on every save means a sub-type
    cannot be deleted at all - the next save puts it straight back, which is
    what happened: pressing × on Thought balloon removed it and the row was
    there again before the panel finished redrawing.

    But "once per project" was too coarse. A project opened before this list
    existed was stamped as seeded from an EMPTY list, so every sub-type added
    to `PRELOADED` afterwards could never reach it: lee, with a project made
    two rounds ago - *"you didnt add teh preloaded sub types"*.

    So what is remembered is not a yes/no but WHICH keys have been offered.
    `offered` is that list. A `PRELOADED` key not in it has never been put in
    front of this person, so it goes in; a key in it was offered once and their
    answer - kept, renamed, deleted - stands. New preloads reach old projects,
    and a deleted one stays deleted. `seed=True` is the new-project case: every
    key is being offered for the first time.
    """
    out: list[dict] = []
    seen = set()
    for s in list(subs or ()):
        if not isinstance(s, dict) or not s.get("key"):
            continue
        key = str(s["key"])
        if key in seen or key in FAMILIES:
            continue                      # a family is not a sub-type of one
        fam = s.get("family") if s.get("family") in FAMILIES else "bubble"
        if len(subs_of(fam, out)) >= SUBS_PER_FAMILY:
            continue          # a family holds five of its own and no more
        seen.add(key)
        out.append({"key": key,
                    "label": str(s.get("label") or key),
                    "family": fam,
                    "color": kind_colour_for_new(fam, out, s.get("color")),
                    "font": str(s.get("font") or "")})
    if not seed and offered is None:
        return out
    already = set() if seed else {str(k) for k in offered}
    for fam, items in PRELOADED.items():
        for key, label in items:
            if key in seen or key in already:
                continue
            if len(subs_of(fam, out)) >= SUBS_PER_FAMILY:
                break
            seen.add(key)
            out.append({"key": key, "label": label, "family": fam,
                        "color": kind_colour_for_new(fam, out, None),
                        "font": ""})
    return out


def kind_colour_for_new(family: str, existing, want=None) -> str:
    """A shade of `family` no other sub-type of it is using.

    `want` is honoured when it is one of the family's shades and free. When
    every shade is taken the first is reused rather than refusing to give a
    colour at all - a sub-type without one cannot be drawn.
    """
    shades = family_shades(family)
    taken = {str(s.get("color") or "").lower()
             for s in subs_of(family, existing)}
    w = str(want or "").lower()
    if w in shades and w not in taken:
        return w
    for c in shades:
        if c not in taken:
            return c
    return shades[0]
