"""The Save-as dialog stops wearing somebody else's logo.

lee photographed the corner of his own Save dialog and said *"make this logo
our logo"*. What he had photographed was **Tk's blue feather**: the dialog is
a Tk window, Tk stamps its own icon on any window that does not set one, and
the one place in this app where the app itself is on screen was advertising
the toolkit.

So the mark is drawn out to a PNG and a Windows `.ico` beside the SVG the
editor inlines (`tools/make_icon.py`), and the dialog wears it.

The drawing is not allowed to matter: a missing file, a Tk too old to read a
PNG, a platform that ignores one of the two calls — the dialog is the point.
"""
import os

import pytest

from mangatl import pickdir

Image = pytest.importorskip("PIL.Image", reason="PIL draws the mark")
from PIL import Image  # noqa: E402
from where import PKG

STATIC = os.path.join(str(PKG), "static")


def test_the_mark_is_there_as_a_picture_as_well_as_a_drawing():
    """The editor inlines the SVG. Tk cannot read one and Windows wants an
    .ico, so the same outline exists as both."""
    assert os.path.isfile(os.path.join(STATIC, "favicon.svg"))
    assert os.path.isfile(os.path.join(STATIC, "icon.png"))
    assert os.path.isfile(os.path.join(STATIC, "icon.ico"))


def test_it_is_big_enough_to_still_be_the_mark_when_it_is_scaled_down():
    im = Image.open(os.path.join(STATIC, "icon.png"))
    assert im.size == (512, 512) and im.mode == "RGBA"


def test_the_windows_icon_carries_every_size_windows_asks_for():
    """A title bar wants 16, a taskbar 32, the desktop 256. An .ico with one
    size in it gets resized by Windows, badly."""
    im = Image.open(os.path.join(STATIC, "icon.ico"))
    sizes = {s for s in im.info.get("sizes", set())}
    for want in (16, 32, 48, 256):
        assert (want, want) in sizes, f"{want} is missing: {sorted(sizes)}"


def test_the_mark_fills_the_square():
    """The SVG's own margin is room for the wordmark beside it. An icon has
    nothing beside it and is looked at at sixteen pixels, so that margin is
    margin nobody can afford."""
    im = Image.open(os.path.join(STATIC, "icon.png"))
    x0, y0, x1, y1 = im.split()[3].getbbox()
    w, h = im.size
    assert max(x1 - x0, y1 - y0) > w * 0.9, "the mark is lost in white space"
    assert abs((w - x1) - x0) <= 2 and abs((h - y1) - y0) <= 2, "and centred"


def test_it_is_the_mark_and_not_a_square():
    """Drawn from the SVG's own path, so the leg falls away into the brush
    stroke: the bottom-left corner of the picture is empty and the top-left
    is not."""
    im = Image.open(os.path.join(STATIC, "icon.png")).split()[3]
    w, h = im.size
    assert im.getpixel((int(w * 0.08), int(h * 0.10))) > 128, "the left arm"
    assert im.getpixel((int(w * 0.06), int(h * 0.95))) == 0, \
        "and nothing under it — the stroke tapers"


def test_the_dialog_puts_it_on():
    src = open(os.path.join(str(PKG),
                            "pickdir.py")).read()
    body = src.split("def _tk_main()", 1)[1]
    assert "_wear_our_own_icon(root)" in body, \
        "drawing an icon nothing wears would change nothing"


class _Hostile:
    """A Tk that refuses both ways of setting an icon."""

    def iconbitmap(self, **kw):
        raise RuntimeError("no")

    def iconphoto(self, *a):
        raise RuntimeError("no")


def test_a_toolkit_that_will_not_wear_it_still_opens_the_dialog():
    pickdir._wear_our_own_icon(_Hostile())      # must not raise


def test_a_missing_icon_file_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(pickdir, "_ICON_DIR", str(tmp_path))
    pickdir._wear_our_own_icon(_Hostile())      # must not raise


def test_the_mark_can_be_drawn_again_from_the_outline():
    """The two pictures are generated, not hand-drawn, so the mark can never
    drift away from the one in the SVG."""
    import importlib.util
    at = os.path.join(str(PKG), "tools", "make_icon.py")
    spec = importlib.util.spec_from_file_location("make_icon", at)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    again = mod.mark(64)
    assert again.size == (64, 64)
    on_disk = Image.open(os.path.join(STATIC, "icon.png")).resize(
        (64, 64), Image.LANCZOS)
    a, b = again.split()[3], on_disk.split()[3]
    assert a.getbbox() == b.getbbox(), "the file is not what the outline draws"
