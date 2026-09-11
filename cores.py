"""Every core, for every detector, every time.

lee: *"is there a way to speed up the find text by optimizing it better or
using more cores or something"*. There was, and it was not more cores - it was
the ones already there.

`import ultralytics` does this, at import, before anything else:

    if not os.environ.get("OMP_NUM_THREADS"):
        os.environ["OMP_NUM_THREADS"] = "1"

It is meant to stop a training job's data workers fighting each other. In
this app it means that from the moment the AnimeText, Manga109 or balloon
checker module is imported, **PyTorch runs on one thread** - CRAFT, AnimeText,
the Manga109 segmenter and DB++ all included - and so does OpenCV. On a
twenty-core machine that is nineteen cores idle for the whole of Find text.
Measured here on two cores, one page: CRAFT 15.2s on one thread, 9.2s on
two; AnimeText 3.9s and 2.4s. On twenty the gap is a different order.

`detect/comictext.py` found half of this once - *"opencv 5.0.0 threads 1
cores 20"* - and put OpenCV's threads back before each forward pass. This is
the other half, and the whole of it in one place:

* `claim()` puts PyTorch and OpenCV back on every core. Called by every
  detector before it runs, because whoever set it to one can set it to one
  again;
* `mangatl/__init__.py` sets `OMP_NUM_THREADS` to the core count before any
  of those imports happen, so ultralytics finds it set and leaves it be.
"""
from __future__ import annotations

import os
import sys


def cores() -> int:
    return os.cpu_count() or 1


def claim_env() -> None:
    """Name the core count in the environment before torch or ultralytics is
    imported. Only when nobody has: a person who set it themselves meant
    it."""
    os.environ.setdefault("OMP_NUM_THREADS", str(cores()))


def claim() -> dict:
    """PyTorch and OpenCV on every core. Returns what each is on, for a log
    line or a test; imports nothing that is not already imported."""
    want = cores()
    got = {}
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            if torch.get_num_threads() < want:
                torch.set_num_threads(want)
            got["torch"] = torch.get_num_threads()
        except Exception:
            pass
    cv2 = sys.modules.get("cv2")
    if cv2 is not None:
        try:
            if cv2.getNumThreads() < want:
                cv2.setNumThreads(want)
            got["cv2"] = cv2.getNumThreads()
        except Exception:
            pass
    return got
