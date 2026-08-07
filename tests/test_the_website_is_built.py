"""`site/index.html` is generated, and has to be the generator's current output.

Its own file, and deliberately only two tests. Everything else about the page
asks what `build.py` MAKES; this asks whether what is on disk is that. Kept
apart because "the copy on disk is stale" would otherwise be the answer to
every question about the page, and a test that fails for one reason whatever
you broke tells you nothing about what you broke.
"""
import importlib.util

from where import PKG

SITE = PKG / "site"


def _build():
    spec = importlib.util.spec_from_file_location("sitebuild", SITE / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_page_on_disk_is_what_the_builder_makes():
    """Editing `index.html` by hand works until the next build, which is the
    worst failure mode there is: the change survives long enough to be
    forgotten and then vanishes."""
    got = (SITE / "index.html").read_text(encoding="utf-8")
    assert _build().build() == got, \
        "run `python site/build.py` — index.html is behind build.py"


def test_the_standalone_copy_carries_its_pictures_with_it():
    """It opens from a file:// URL with nothing beside it, so every asset has
    to be inlined — one `assets/` left in it is one broken picture.

    Asked of the FUNCTION rather than of the file on disk. The standalone copy
    is the same page with three megabytes of base64 in it, so it is not
    committed — every rebuild would be a three-megabyte diff — and a test that
    read it would fail on a fresh clone for a reason that has nothing to do
    with the code.
    """
    b = _build()
    s = b.standalone(b.build())
    assert "assets/" not in s
    assert "data:image/" in s and "data:font/" in s


def test_a_broken_picture_stops_the_build(tmp_path, monkeypatch, capsys):
    """A picture the page asks for and `assets/` does not have goes live as a
    broken image — the one fault a visitor sees before they read a word.

    An empty SLOT is a different thing and is fine: it is a picture lee has
    not taken yet, and it is drawn as a labelled hole. The exit code is where
    that difference is said out loud, because that is the form a deploy
    workflow can read.
    """
    import runpy
    import pytest
    # The real thing, with one asset hidden: `mark.svg` is inlined into the
    # header and the footer, so the page cannot stop asking for it.
    real = _build().have

    def blind(name):
        return False if name == "mark.svg" else real(name)

    mod = _build()
    monkeypatch.setattr(mod, "have", blind)
    html = mod.build()
    assert "assets/mark.svg" in html or mod.missing(html) != []
    assert mod.missing(html), "the hidden asset should be reported missing"
    # ...and with nothing hidden, nothing is reported.
    assert _build().missing(_build().build()) == []


def test_the_build_says_what_is_still_wanted():
    """The list of shots lee has yet to take is an answer the build GIVES, not
    a list somebody keeps by hand beside it."""
    b = _build()
    b.WANTED.clear()
    b.build()
    assert b.WANTED
    src = (SITE / "build.py").read_text(encoding="utf-8")
    assert "raise SystemExit(1 if broken else 0)" in src, \
        "a broken reference has to reach the exit code"
