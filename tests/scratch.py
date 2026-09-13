"""A scratch folder name that belongs to this worker and nobody else.

The suite runs under `-n 2`, and xdist hands out individual TESTS, not whole
files - so two tests written in the same file run at the same moment in two
processes. Every one of them that built its working folder from a fixed name
was sharing that folder with the other: the first to finish deleted it while
the second was still reading, and the run died with `FileNotFoundError` on a
page that had certainly just been written. It looked like a bug in the editor.
It was two tests standing in one room.

The worker id is empty when the suite runs in a single process.

**And the room is outside the package.** The name used to be relative, and
the suite runs from the repository folder - which IS the package - so every
scratch project was built inside the tree that three tests read end to end.
Under `-n auto` on CI, `test_nothing_imports_the_removed_module` listed
`_tmp_warm_silentgw3` while another worker's test was deleting it, and Python
3.11's `rglob` raised `FileNotFoundError` on a folder that had nothing to do
with the test that failed. Beside the suite's fake home in the temp folder, a
scratch project is in nobody's walk.
"""
import os
import tempfile

_BASE = os.path.join(tempfile.gettempdir(), "mangatl-test-scratch")


def scratch(name: str) -> str:
    os.makedirs(_BASE, exist_ok=True)
    return os.path.join(_BASE,
                        name + os.environ.get("PYTEST_XDIST_WORKER", ""))
