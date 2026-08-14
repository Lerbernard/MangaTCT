"""A chapter whose files are named in Korean.

lee loaded a manhwa - 120 tiles, all named `이번_생은_가주가_되겠습니다_227화_-_웹툰_이미지_N.jpeg`
- and the console filled up with one line per file::

    can't open/read file: check file path/integrity

for every one of the 120, each printed with the name in the mojibake a Windows
console makes of UTF-8. The files were there. They were fine.

`cv2.imread` is the problem, and only on Windows: it hands the path down to the
C runtime as BYTES in the machine's ANSI code page, and 가 has no spelling in a
Western one. The name is mangled on the way and `fopen` is asked for a file
nobody has. The same call on the same file works here, because this code page
is UTF-8 - which is why nothing ever caught it.

What it cost, in the order it hurts:

* **`add_uploaded` DELETED them.** It writes the file, reads it back to check
  it is an image, and removes it when that comes back empty. Every tile of a
  Korean-named chapter was written and then thrown away, and the person was
  told the file was unusable.
* **A Korean webtoon could never be re-cut.** `strip.py` reads every tile to
  build the row profile; all of them empty means no gutters, no cuts, and the
  re-cut quietly declines.
* **`rescan` recorded every page as 0x0**, so `looks_sliced` was answering
  about a chapter of nothing.

So nothing reads an image by path any more. `imgio.imread` opens the file in
Python - which goes through the wide API - and hands the BYTES to `imdecode`,
which never sees a name.

The tests below run `cv2.imread` broken on purpose. That is not a trick: it is
exactly the machine lee is on, and it is the only way to have this fail here
before it fails there.
"""
import os
import re

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import imgio
from where import PKG

# What lee's files are actually called.
KOREAN = "이번_생은_가주가_되겠습니다_227화_-_웹툰_이미지_%d.jpeg"


def _some_art(h=140, w=90, seed=3):
    rng = np.random.default_rng(seed)
    return np.repeat(rng.integers(30, 220, (h, w, 1), dtype=np.uint8), 3, axis=2)


@pytest.fixture()
def blind_cv2(monkeypatch):
    """`cv2.imread` and `cv2.imwrite` as Windows has them for these names:
    the read comes back empty and the write refuses."""
    monkeypatch.setattr(cv2, "imread", lambda *a, **k: None)
    monkeypatch.setattr(cv2, "imwrite", lambda *a, **k: False)


# ------------------------------------------------------------------ the reader

def test_a_korean_name_is_read(tmp_path, blind_cv2):
    art = _some_art()
    f = str(tmp_path / (KOREAN % 1))
    assert imgio.imwrite(f, art)
    got = imgio.imread(f)
    assert got is not None, "the file is right there"
    assert got.shape == art.shape


def test_it_is_the_same_picture(tmp_path):
    """Not merely readable. A PNG round trip has to be the pixels back."""
    art = _some_art()
    f = str(tmp_path / "그림.png")
    assert imgio.imwrite(f, art)
    assert np.array_equal(imgio.imread(f), art)


def test_the_flags_still_mean_what_they_meant(tmp_path):
    f = str(tmp_path / "회색.png")
    imgio.imwrite(f, _some_art())
    assert imgio.imread(f, cv2.IMREAD_GRAYSCALE).ndim == 2
    assert imgio.imread(f).ndim == 3


def test_a_file_that_is_not_there_is_still_None(tmp_path):
    """Every caller in the app reads None as "not usable". That has to keep
    meaning what it meant, or a missing page turns into a crash instead."""
    assert imgio.imread(str(tmp_path / "없음.png")) is None


def test_a_file_that_is_not_a_picture_is_None(tmp_path):
    f = tmp_path / "notes.png"
    f.write_bytes(b"this is not a png, it is a sentence")
    assert imgio.imread(str(f)) is None


def test_an_empty_file_is_None(tmp_path):
    """Nought bytes is the one input that RAISES out of `imdecode` - an
    assertion, not an empty answer - rather than coming back None like every
    other kind of rubbish. A half-written upload, or a file still being
    copied in, must not take the run down with it."""
    f = tmp_path / "half.png"
    f.write_bytes(b"")
    assert imgio.imread(str(f)) is None


def test_half_a_png_is_None(tmp_path):
    """The other half of that: truncated part-way, which comes back empty
    rather than raising. Both roads have to end at None."""
    art = _some_art()
    whole = cv2.imencode(".png", art)[1].tobytes()
    f = tmp_path / "truncated.png"
    f.write_bytes(whole[:len(whole) // 2])
    assert imgio.imread(str(f)) is None


def test_a_folder_is_not_a_page(tmp_path):
    d = tmp_path / "폴더.png"
    d.mkdir()
    assert imgio.imread(str(d)) is None


# ------------------------------------------------------------------ the writer

def test_writing_into_a_korean_folder(tmp_path, blind_cv2):
    """The way out mangles the same way, and it is worse there: the write
    fails, `imwrite` says False, and False out of it reads as "wrong format"."""
    d = tmp_path / "한국어"
    d.mkdir()
    f = str(d / "page001.png")
    assert imgio.imwrite(f, _some_art())
    assert os.path.isfile(f)


def test_the_extension_chooses_the_format(tmp_path):
    a = str(tmp_path / "장.jpg")
    b = str(tmp_path / "장.png")
    art = _some_art()
    imgio.imwrite(a, art)
    imgio.imwrite(b, art)
    assert open(a, "rb").read(2) == b"\xff\xd8", "a .jpg has to be a JPEG"
    assert open(b, "rb").read(4) == b"\x89PNG"


def test_a_write_that_cannot_land_says_so(tmp_path):
    assert not imgio.imwrite(str(tmp_path / "nope" / "x.png"), _some_art())


def test_a_format_nobody_can_encode_says_so(tmp_path):
    """`imencode` raises on an extension it does not know rather than
    answering False. False is the answer every caller here reads."""
    assert not imgio.imwrite(str(tmp_path / "page.xyz"), _some_art())


# ------------------------------------------------- and the app goes through it

def test_an_uploaded_korean_page_is_not_deleted(tmp_path, blind_cv2):
    """The worst of them. lee's tile was written to disk, read back with
    `cv2.imread`, found to be nothing, and REMOVED - his file, gone, with
    "unusable" as the explanation."""
    from mangatl.project import Project

    p = Project(None, str(tmp_path / "out"))
    name = KOREAN % 7
    data = cv2.imencode(".jpg", _some_art(200, 120))[1].tobytes()
    i = p.add_uploaded(name, data)

    assert i == 0, "the page must be added"
    assert os.path.isfile(os.path.join(p.upload_dir(), name)), \
        "the file was deleted"
    assert p.pages[0].width == 120 and p.pages[0].height == 200, \
        "a page recorded as 0x0 is a page nothing downstream can measure"


def test_a_folder_of_korean_pages_is_measured(tmp_path, blind_cv2):
    """`rescan` is what a project comes back to on open. Sizes of 0x0 there
    are what `looks_sliced` was being asked about."""
    from mangatl.project import Project

    d = tmp_path / "chapter"
    d.mkdir()
    for n in range(1, 4):
        imgio.imwrite(str(d / (KOREAN % n)), _some_art(300, 150, seed=n))
    p = Project(None, str(tmp_path / "out"))
    assert p.use_folder(str(d)) == 3
    assert all(pg.width == 150 and pg.height == 300 for pg in p.pages), \
        [(pg.name, pg.width, pg.height) for pg in p.pages]


def test_a_korean_webtoon_can_be_re_cut(tmp_path, blind_cv2):
    """The whole point of the strip fixer, on the chapter it was reported on.
    Reading nothing gives no row profile, no gutters and no cuts, so it simply
    declined - and said nothing, because declining is the normal answer."""
    from mangatl import strip

    d = tmp_path / "tiles"
    d.mkdir()
    # A strip with real gutters, sliced by count the way a webtoon site does.
    rng = np.random.default_rng(11)
    rows = []
    for i in range(12):
        rows.append(np.repeat(rng.integers(150, 220, (700 + i * 90, 600, 1),
                                           dtype=np.uint8), 3, axis=2))
        rows.append(np.full((40, 600, 3), 255, np.uint8))
    img = np.vstack(rows)
    tiles = []
    for n, a in enumerate(range(0, len(img), 1000), 1):
        f = str(d / (KOREAN % n))
        imgio.imwrite(f, img[a:a + 1000])
        tiles.append(f)

    rep = strip.restitch(tiles, str(tmp_path / "pages"), target=2400,
                         ceiling=6000)
    assert len(rep["pages"]) > 1, "a Korean-named strip is still a strip"
    back = [imgio.imread(os.path.join(str(tmp_path / "pages"), n))
            for n in rep["pages"]]
    assert sum(len(x) for x in back) == len(img)


# --------------------------------------------------------------- and it stays

# The app's own modules. Not the tests, which read files they made themselves
# with names they chose, and not `imgio` itself, which is where the one
# remaining call lives.
_MINE = ["editor.py", "project.py", "strip.py", "pipeline.py", "render.py",
         "typeset.py", "inpaint.py", "ocr.py", "sfx.py", "bundle.py",
         "manual.py", "diag.py", "score.py", "interactive.py",
         "detect/classical.py", "detect/balloon.py", "detect/comictext.py",
         "detect/yolo.py"]


def test_nothing_reads_an_image_by_path_any_more():
    """The guard. One bare `cv2.imread` put back anywhere is this bug back,
    and it will not show up on this machine when it happens."""
    bad = []
    for rel in _MINE:
        f = PKG / rel
        if not f.is_file():
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bcv2\.(imread|imwrite)\s*\(", line):
                bad.append(f"{rel}:{n}: {line.strip()}")
    assert not bad, "use imgio.imread / imgio.imwrite:\n" + "\n".join(bad)


def test_imgio_is_the_one_place_that_does_it():
    """...and it does, because a helper that quietly stopped calling OpenCV
    would pass the guard above while decoding nothing."""
    src = (PKG / "imgio.py").read_text(encoding="utf-8")
    assert "cv2.imdecode(" in src and "cv2.imencode(" in src
