"""Find text on every core, not one.

lee: *"is there a way to speed up the find text by optimizing it better or
using more cores or something"*. `import ultralytics` sets
`OMP_NUM_THREADS=1` when nobody has, and from then on PyTorch - CRAFT,
AnimeText, the Manga109 segmenter, DB++ - runs on one core, on a machine
with twenty. Measured on two cores: CRAFT 15.2s a page on one thread, 9.2s
on two; AnimeText 3.9s and 2.4s.

Three things hold it fixed: the package names the core count in the
environment before ultralytics can, every detector puts the threads back
before it runs (whoever set them to one can do it again), and the launcher
says the same thing from outside for an app version from before this.
"""
import os
import subprocess
import sys

import pytest

from where import PKG
from mangatl import cores


def test_claim_puts_torch_and_opencv_back_on_every_core(monkeypatch):
    torch = pytest.importorskip("torch")
    import cv2
    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    got = cores.claim()
    assert got["torch"] == cores.cores() == os.cpu_count()
    assert got["cv2"] == cores.cores()
    assert torch.get_num_threads() == cores.cores()


def test_claim_env_names_the_cores_and_respects_a_person_who_set_it(monkeypatch):
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    cores.claim_env()
    assert os.environ["OMP_NUM_THREADS"] == str(os.cpu_count() or 1)
    monkeypatch.setenv("OMP_NUM_THREADS", "3")
    cores.claim_env()
    assert os.environ["OMP_NUM_THREADS"] == "3", "somebody who set it meant it"


def test_importing_the_package_first_keeps_ultralytics_from_throttling_torch():
    """In a fresh interpreter, the way the editor starts: the package, then
    the thing that would set the threads to one, then torch's own count."""
    pytest.importorskip("ultralytics")
    pytest.importorskip("torch")
    code = ("import os, sys\n"
            "os.environ.pop('OMP_NUM_THREADS', None)\n"
            "import mangatl\n"
            "import ultralytics, torch\n"
            "print(os.environ.get('OMP_NUM_THREADS'), torch.get_num_threads(), os.cpu_count())\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=str(PKG.parent), timeout=600,
                       env={**os.environ, "PYTHONPATH": str(PKG.parent)})
    assert r.returncode == 0, r.stderr[-2000:]
    env, threads, n = r.stdout.strip().split()[-3:]
    assert env == n and threads == n, r.stdout


@pytest.mark.parametrize("path", [
    "detect/craft.py", "detect/animetext.py", "detect/mangaseg.py",
    "detect/dbtext.py", "detect/yolo.py", "detect/comictext.py", "balloonck.py",
])
def test_every_detector_claims_the_cores_before_it_runs(path):
    src = (PKG / path).read_text(encoding="utf-8")
    assert "cores.claim()" in src, path


def test_the_launcher_says_it_from_outside_too():
    sys.path.insert(0, str(PKG / "launcher"))
    import mangatct_launcher as L
    p = L.paths("/tmp/x")
    env = L.editor_env(p)
    assert env["OMP_NUM_THREADS"] == str(os.cpu_count() or 1)
