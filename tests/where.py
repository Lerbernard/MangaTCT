"""Where the app's own files are, whichever way the tree is laid out.

Thirty-four test files used to work this out for themselves, by going up out
of `tests` and then back down into a folder named for the package - which is
true only when `tests/` sits BESIDE the package rather than inside it. In the
repository it is inside it: the repository root *is* the package, so going up
one lands on the package already and the step back down walks into a folder
that is not there. Every one of those files passed in a checkout laid out one
way and could not find a file in the other, which is the worst kind of
failure: it is not about the thing being tested at all.

Asking the package where it lives has neither problem. `mangatl.__file__` is
the `__init__.py` that was actually imported, so this is right in a checkout,
in an installed copy, and in whatever layout comes next.
"""
from pathlib import Path

import mangatl

PKG = Path(mangatl.__file__).resolve().parent
STATIC = PKG / "static"
JS = STATIC / "js"
CSS = STATIC / "css"
EDITOR_HTML = STATIC / "editor.html"
