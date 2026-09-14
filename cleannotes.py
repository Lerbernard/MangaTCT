"""The cleaner's own notes on a box, and keeping them from piling up.

lee, of the red panel under a box whose notes said the same sentence twice:
*"remoev this"*.

Two things were wrong with that panel. The sentence itself - "the typesetting
here is hard to tell from the artwork, so only the strokes were erased - check
it" - was said about a clean that had gone fine, on every box the careful
path took, and a warning that is always there stops being read. And every note
the cleaner writes was APPENDED to whatever the box already carried: the notes
are saved with the box and come back with it, so each clean said its piece
again on top of the last one. His chapter had 43 boxes repeating a sentence.

So:

* the sentence is not written any more (`inpaint.py`, where the core-only
  clean is) and is taken out of notes already saved (`without_retired`);
* a clean takes the notes an EARLIER clean left before it writes its own
  (`without_clean_notes`), so a note says what the last clean found, once;
* notes that are not the cleaner's - the reader's, the labeller's, the
  fitter's - are left exactly as they are. The cleaner's are matched by their
  whole wording, not by a prefix, because other notes run straight on after
  them ("...paint it out in Edit; the outline runs off its balloon").

Its own module so `project.py`, which loads every box, does not have to import
the cleaner to tidy a string.
"""
from __future__ import annotations

import re

# Said once, and not any more.
RETIRED = (
    re.compile(r"\s*clean: the typesetting here is hard to tell from the "
               r"artwork, so only the strokes were erased(?:\s*—\s*check it)?"),
)

# Every note `inpaint_page` writes, by its wording.
CLEAN_NOTES = (
    re.compile(r"\s*clean: fell back to the detector's own text mask here"),
    re.compile(r"\s*screentone: cleaned by pattern copy, worth a look"),
    re.compile(r"\s*clean: the page reads as still having writing over most of "
               r"this box — check it, it was left as it is"),
    re.compile(r"\s*ghost: source text is still faintly visible after the .*?"
               r" — paint it out in Edit"),
) + RETIRED


def without_retired(flagged):
    """Saved notes minus the retired sentence, and minus a cleaner note said
    more than once. For notes coming off the disk."""
    if not flagged:
        return flagged
    text = str(flagged)
    for pat in RETIRED:
        text = pat.sub("", text)
    for pat in CLEAN_NOTES:
        said = []

        def once(m):
            if said:
                return ""
            said.append(True)
            return m.group(0)
        text = pat.sub(once, text)
    return text.strip() or None


def without_clean_notes(flagged):
    """Notes with every cleaner note taken out - for a clean about to write
    what it found this time."""
    if not flagged:
        return flagged
    text = str(flagged)
    for pat in CLEAN_NOTES:
        text = pat.sub("", text)
    return text.strip() or None
