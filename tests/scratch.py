"""A scratch folder name that belongs to this worker and nobody else.

The suite runs under `-n 2`, and xdist hands out individual TESTS, not whole
files - so two tests written in the same file run at the same moment in two
processes. Every one of them that built its working folder from a fixed name
was sharing that folder with the other: the first to finish deleted it while
the second was still reading, and the run died with `FileNotFoundError` on a
page that had certainly just been written. It looked like a bug in the editor.
It was two tests standing in one room.

The worker id is empty when the suite runs in a single process, so the names
are exactly what they were there.
"""
import os


def scratch(name: str) -> str:
    return name + os.environ.get("PYTEST_XDIST_WORKER", "")
