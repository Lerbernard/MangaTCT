"""mangatl - manga translation pipeline.

Detect speech bubbles, read the Japanese, translate a whole page at once,
erase the source text, and typeset English back into the bubbles.
"""
from __future__ import annotations

import os as _os

__version__ = "0.2.0"


def _load_dotenv(filename: str = ".env") -> str | None:
    """Read KEY=value lines from a .env file into the environment.

    Looks in the current working directory first, then beside the package, so
    it works whether you run from the project folder or somewhere else.
    Existing environment variables always win - a real shell variable
    overrides the file, which is what you want for CI and one-off overrides.

    Returns the path it loaded, or None.
    """
    here = _os.path.dirname(_os.path.abspath(__file__))
    candidates = [
        _os.path.join(_os.getcwd(), filename),
        _os.path.join(_os.path.dirname(here), filename),  # project root
        _os.path.join(here, filename),
    ]
    for path in candidates:
        if not _os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key:
                        _os.environ.setdefault(key, val)
        except OSError:
            continue
        return path
    return None


DOTENV_PATH = _load_dotenv()

# Before torch or ultralytics is imported by anything below: ultralytics sets
# OMP_NUM_THREADS=1 at import if nobody has, and PyTorch then runs on one core
# for the life of the process. See `cores.py`.
from . import cores as _cores                          # noqa: E402
_cores.claim_env()

from .pipeline import RunConfig, report, run          # noqa: E402
from .translate import SeriesContext                  # noqa: E402
from .models import Page, TextLayout, TextRegion       # noqa: E402

__all__ = [
    "Page",
    "TextRegion",
    "TextLayout",
    "RunConfig",
    "run",
    "report",
    "SeriesContext",
    "DOTENV_PATH",
    "__version__",
]
