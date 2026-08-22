"""Removed. Nothing imports this file, and it does nothing if you do.

There was an AI box pass at Find text here. The page went out to Claude with
every measured box outlined and numbered, and the model answered with a kind for
each box and a list of boxes holding no writing at all - two powers, no third
one; it could not move a corner or add a box. Some 1500 lines: the labelled-PNG
builder, the prompt, the two fences that made "it cannot change the geometry" an
arithmetic fact instead of a request, and an older "find" mode in which the model
listed the writing itself and the measuring was thrown away.

lee watched it run on his own chapter and said: "nvm remove it its pretty bad
remove the ai". So it is out. Find text is measurement from the first pass to
the last - free, offline, and it gives the same answer twice.

This file is left as a note rather than deleted because nothing here can delete
a file on lee's machine; he can drop it, and tests/test_ai_boxes.py with it,
whenever he likes. tests/test_ai_boxes.py is now a guard that fails if the pass
is ever wired back in without being thought about again.

None of the OTHER AI in this project was touched, and none of it lived here:
the reader (ocr.py), the translator (translate.py), the proofreader and the
hosted cleaner are all where they were and all still on. It was only ever the
box pass that was bad.

What the removal gives up, said plainly so nobody re-adds it by accident:
nothing now labels a box by looking at the DRAWING. A caption inside a ruled box
is called a balloon because a rule was measured round it, and typesetting brushed
straight onto artwork is called freefloat unless comic-text-detector's own kind
head says otherwise - that is the `auto_kind` setting, which is measurement too
and is still on. Against that, Kind is one click on any box in the editor, and
clicking it has never moved a corner. Which was the whole problem with the AI.
"""
