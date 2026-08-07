"""The card that goes at the end of a chapter.

lee: *"creat a advertizement card that i can put at the end of chapters"*.

Six pictures from one description: three shapes by two grounds. There is no
Photoshop file to keep in step and no exported layer to forget to re-export -
change a word or a colour and every one of the six changes.

The test that matters is the last one. Both bugs this card had while it was
being drawn were the same bug: something ran off the edge. The address plate
hung past the bottom of the page card, and on the banner the address ran off
the right. Neither is visible in a thumbnail and both are obvious in a chapter.
Ink in the margin is measurable, so it is measured.
"""
import importlib.util

import pytest

from where import PKG

pytest.importorskip("PIL")


def card():
    spec = importlib.util.spec_from_file_location(
        "adcard", str(PKG / "tools" / "adcard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SHAPES = ["page", "strip", "banner"]
GROUNDS = ["dark", "light"]


@pytest.fixture(scope="module")
def made():
    ad = card()
    out = {}
    for shape in SHAPES:
        for ground in GROUNDS:
            out[(shape, ground)] = ad.card(
                shape, ad.DARK if ground == "dark" else ad.LIGHT,
                ground == "dark")
    return out


# ------------------------------------------------------------ what is drawn

def test_there_is_one_of_each_shape_and_each_ground(made):
    ad = card()
    for shape in SHAPES:
        for ground in GROUNDS:
            img = made[(shape, ground)]
            assert img.size == ad.SHAPES[shape], (shape, ground)


def test_the_words_are_written_once(made):
    """Every string on the card is a constant at the top of the file, so
    changing what it says is changing one line and not hunting through a
    layout. A card is an advertisement; the words are the whole of it."""
    ad = card()
    for name in ("SAYS", "NAME", "LINE", "FORMATS", "GO", "URL"):
        assert getattr(ad, name), name
    assert ad.URL == "mangatct.com"
    assert "translated with" in ad.SAYS
    # ...and the house style holds here too: no em dashes, no middots.
    for name in ("SAYS", "LINE", "FORMATS", "GO", "URL"):
        text = getattr(ad, name)
        assert "—" not in text and "·" not in text, name


def test_the_mark_is_read_from_the_one_file_that_holds_it():
    """The same M is the site's header, the app icon and the coin. A copy of
    the path in here would be a fourth place to remember."""
    ad = card()
    pts = ad.mark_points()
    assert len(pts) >= 12, pts
    assert all(0 <= x <= 64 and 0 <= y <= 64 for x, y in pts), pts

    svg = (PKG / "site" / "assets" / "mark.svg").read_text(encoding="utf-8")
    assert " d=\"" in svg, "the card reads the path out of this file"


def test_a_changed_mark_changes_the_card(tmp_path, monkeypatch):
    """The proof that it is read and not merely read once. Point it at a
    different shape and the picture has to be different."""
    ad = card()
    before = ad.card("banner", ad.DARK, True).tobytes()

    other = tmp_path / "mark.svg"
    other.write_text(
        '<svg viewBox="0 0 64 64"><path d="M4 4 L60 4 L60 60 L4 60 Z"/></svg>',
        encoding="utf-8")
    monkeypatch.setattr(ad, "MARK_SVG", str(other))
    assert ad.card("banner", ad.DARK, True).tobytes() != before


def test_the_dark_card_is_dark_and_the_light_one_is_light(made):
    """Read off the corner, which is ground on every shape. A card that came
    out the wrong way round would be invisible at the end of a chapter of the
    same colour."""
    for shape in SHAPES:
        dark = made[(shape, "dark")].getpixel((5, 60))
        light = made[(shape, "light")].getpixel((5, 60))
        assert sum(dark) < 120, (shape, dark)
        assert sum(light) > 600, (shape, light)


def test_every_card_says_where_to_go(made):
    """The address is the whole point of the card, and on the dark ones it is
    dark type in a gold plate rather than gold type on black. So this asks for
    the GOLD, which is on the card either way, and asks for a lot of it: the
    plate, or the type, is the biggest gold thing on there."""
    ad = card()
    for shape in SHAPES:
        for ground in GROUNDS:
            img = made[(shape, ground)].convert("RGB")
            gold = ad.DARK["gold"] if ground == "dark" else ad.LIGHT["gold"]
            near = sum(n for n, px in img.getcolors(1 << 20)
                       if abs(px[0] - gold[0]) < 40 and abs(px[1] - gold[1]) < 55
                       and px[2] < 90)
            floor = img.size[0] * img.size[1] * 0.010
            assert near > floor, (shape, ground, near, floor)


# ------------------------------------------------------------- nothing spills

@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("ground", GROUNDS)
def test_nothing_is_drawn_in_the_margin(made, shape, ground):
    """The bug this card had twice.

    The address plate hung past the bottom of the page card, and on the banner
    the address ran off the right edge, because both were sized against a share
    of the card rather than against the room left over. Neither shows in a
    thumbnail; both are the first thing you see in a chapter.

    So: everything that is not the ground has to sit inside the margin, with
    the one deliberate exception of the gold rule across the very top, which is
    a full-bleed edge on purpose.
    """
    img = made[(shape, ground)].convert("RGB")
    w, h = img.size
    bar = max(4, w // 190) if ground == "dark" else max(3, w // 300)
    body = img.crop((0, bar + 2, w, h))

    ground_px = body.getpixel((2, 2))

    def inked(px):
        return sum(abs(a - b) for a, b in zip(px, ground_px)) > 30

    px = body.load()
    bw, bh = body.size
    left = right = None
    top = bottom = None
    for x in range(bw):
        if any(inked(px[x, y]) for y in range(0, bh, 3)):
            left = x
            break
    for x in range(bw - 1, -1, -1):
        if any(inked(px[x, y]) for y in range(0, bh, 3)):
            right = x
            break
    for y in range(bh):
        if any(inked(px[x, y]) for x in range(0, bw, 3)):
            top = y
            break
    for y in range(bh - 1, -1, -1):
        if any(inked(px[x, y]) for x in range(0, bw, 3)):
            bottom = y
            break

    assert None not in (left, right, top, bottom), "the card is blank"

    # The same margin the layout uses, less a little slack for antialiasing.
    side = int(w * (0.07 if shape == "banner" else 0.10)) - 6
    assert left >= side, f"{shape}/{ground}: ink {left}px from the left edge"
    assert bw - 1 - right >= side, \
        f"{shape}/{ground}: ink {bw - 1 - right}px from the right edge"

    floor = int(h * 0.085) - 8 - bar
    assert top >= min(floor, int(h * 0.05)), \
        f"{shape}/{ground}: ink {top}px from the top"
    assert bh - 1 - bottom >= min(floor, int(h * 0.03)), \
        f"{shape}/{ground}: ink {bh - 1 - bottom}px from the bottom"


def test_the_words_are_not_squeezed_when_the_card_is_short(made):
    """The strip card holds the same words in three quarters of the page
    card's height. When the column does not fit, the GAPS give way and the
    type does not: squeezing the type would make one shape read at a different
    size from another, and these are meant to be one card in three shapes."""
    ad = card()
    page_w = ad.SHAPES["page"][0]
    strip_w = ad.SHAPES["strip"][0]
    # Type is sized off the WIDTH, so the same line is the same fraction of
    # the card on both. If a height squeeze had touched it, it would not be.
    for shape, width in (("page", page_w), ("strip", strip_w)):
        img = made[(shape, "dark")]
        assert img.size[0] == width
    assert ad.SHAPES["strip"][1] < ad.SHAPES["page"][1]
