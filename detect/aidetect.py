"""Removed. Nothing imports this file, and it does nothing if you do.

There was a second AI pass at Find text here - the one built after the first
was taken out, and deliberately not the same thing. It asked a model where the
writing was and what kind each piece was, in overlapping tiles down a webtoon
page, and then SNAPPED every rectangle it got back onto the ink underneath, so
a loose answer could not put a box on the artwork. Some 300 lines: the tiling,
the prompt, the corner reader that coped with three different orderings
(Gemini answers y-first), the reading-orientation vote, the snap and the dedup.

lee: *"remoeve teh whole ai box deection and just keep what we have now"*.

So Find text is measurement again, from the first pass to the last - free,
offline, no key, no coins, and it gives the same answer twice. What "what we
have now" means, and it is a good deal more than it was a week ago:

  * the double balloon comes apart, measured on all 142 blocks of chapter 1
  * a sound-effect box covers the whole stroke rather than clipping it
  * a caption comes back as a caption, 16 of the 23 on that chapter
  * the coverage pass takes a second opinion from CRAFT before keeping a box
  * counted by eye over eight pages, 29 of 30 balloons, captions and asides
    are boxed

This file is left as a note rather than deleted because nothing here can delete
a file on lee's machine; he can drop it, and
`tests/test_the_ai_find_pass_is_gone.py` with it, whenever he likes. That test
is now a guard: it fails if the pass is wired back in without somebody coming
here and saying out loud that it is being re-added.

Gone with it: the `find_with` setting, the FIND TEXT service menu on the
Settings page, the `find_model` / `find_backend` / `find_base_url` /
`find_key` settings, `find` as one of `AI_STEPS`, `finding_with_ai`,
`prepare_ai_find`, `find_warning`, and the pricing hook that charged a run of
Find text against a model. A project.json saved while any of that existed just
carries settings nothing reads.

None of the OTHER AI in this project was touched, and none of it lived here:
the reader (ocr.py), the translator (translate.py), the proofreader and the
hosted cleaner are all where they were and all still on. `detect/craft.py` is
NOT AI in this sense either - it is a text detector that runs offline on the
machine, it has no key and costs no coins, and it is doing load-bearing work in
the measured pass.
"""
