"""Reading an image whose filename is not ASCII.

lee uploaded a Korean webtoon and every one of its 120 tiles came back as::

    can't open/read file: check file path/integrity

while sitting right there on disk, and the editor answered
`IndexError: list index out of range` on top of it.

The files were fine. `cv2.imread` is the problem: on Windows it hands the path
to the C runtime as BYTES in the machine's ANSI code page, and
`이번 생은 가주가 되겠습니다` has no spelling in a Western one. The name is
mangled on the way down and `fopen` is asked for a file nobody has. Same call
on the same file works on Linux, where the code page is UTF-8, which is why
this never showed up here.

Reading the bytes in Python and handing those to `imdecode` sidesteps the path
altogether: `open()` goes through the wide API and OpenCV never sees a name.

Everything that reads an image goes through here. A bare `cv2.imread` anywhere
in the app is the bug coming back — `test_a_korean_filename_is_a_filename.py`
fails the build if one appears.
"""
from __future__ import annotations

import os

import cv2
import numpy as np


def imread(path: str, flags: int = cv2.IMREAD_COLOR):
    """`cv2.imread`, and it works when the name is Korean.

    Returns None exactly where `cv2.imread` would: the file is missing, is not
    an image, or is truncated past use. A caller that treats None as "unusable"
    is still right — it just no longer gets told that about a perfectly good
    file with an accent in its name.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    try:
        return cv2.imdecode(np.frombuffer(data, np.uint8), flags)
    except cv2.error:
        # A file the decoder cannot make sense of usually comes back empty,
        # but not always: nought bytes — a half-finished upload, a file still
        # being written — trips an assertion inside `imdecode` instead. That
        # is still "not an image" as far as anybody upstream is concerned, and
        # it must not take a whole run down with it.
        return None


def imwrite(path: str, img, params: list[int] | None = None) -> bool:
    """`cv2.imwrite`, and it works when the FOLDER is Korean.

    The same mangling happens on the way out, and it is worse there: the write
    fails, `imwrite` returns False, and the usual reading of a False from it is
    that the format was wrong. `imencode` makes the bytes and Python puts them
    where they go.
    """
    ext = os.path.splitext(path)[1] or ".png"
    try:
        ok, buf = cv2.imencode(ext, img, params or [])
    except cv2.error:
        return False
    if not ok:
        return False
    try:
        with open(path, "wb") as fh:
            fh.write(buf.tobytes())
    except OSError:
        return False
    return True
