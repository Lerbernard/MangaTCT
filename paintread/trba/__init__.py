"""TRBA, vendored from COO-Comic-Onomatopoeia, unchanged except for imports.

    https://github.com/ku21fan/COO-Comic-Onomatopoeia  (ECCV 2022)
    MIT License, Copyright (c) 2021 Baek JeongHun -- see LICENSE beside this
    file, and the entry in the project's NOTICE.

Only what is needed to BUILD the network is here: `model.py` and the four
`modules/`. The training loop, the lmdb dataset reader, the evaluation harness
and the demo script are not, because a reader that loads a checkpoint and
answers a crop needs none of them.

The one edit is `from modules.x` -> `from .modules.x` in `model.py`, so this
imports as a package rather than off the working directory.

`charset.txt` is the authors' `Onomatopoeia_train_char_set.txt`: 182 characters
of kana and marks, and NO KANJI - which is not a limitation to work around, it
is the fact `paintread.prefer` decides on.

Everything the app calls is in `paintread/__init__.py`; nothing outside this
folder should import from here.
"""
