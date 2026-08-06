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
    to be inlined — one `assets/` left in it is one broken picture."""
    s = (SITE / "mangatct-site-standalone.html").read_text(encoding="utf-8")
    assert "assets/" not in s
    assert "data:image/" in s and "data:font/" in s
