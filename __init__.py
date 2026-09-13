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

# The names below are handed out on first use rather than imported here.
# `import mangatl` happens before anything else in every process - the app
# window's too - and importing `pipeline` pulled in OpenCV, NumPy, PIL and the
# whole reading-and-typesetting stack, about half a second, for a window that
# only needs to know where the person's folder is. lee: *"optimaze the app make
# it faster and moother dont chnage teh fuctionality"*. `from mangatl import
# run` and `mangatl.Page` work exactly as before; the import simply happens the
# first time one of them is asked for.
_LAZY = {"RunConfig": "pipeline", "report": "pipeline", "run": "pipeline",
         "SeriesContext": "translate",
         "Page": "models", "TextLayout": "models", "TextRegion": "models"}


def __getattr__(name: str):
    where = _LAZY.get(name)
    if where is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    value = getattr(importlib.import_module(f".{where}", __name__), name)
    globals()[name] = value
    return value


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
