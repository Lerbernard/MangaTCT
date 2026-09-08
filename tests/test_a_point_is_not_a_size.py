# -*- coding: utf-8 -*-
"""One number, ten faces, ten different heights - and the fix for it.

lee: *"also can you make rhe tyesetting addap to teh fonsts some font have
smaller text and some have bigger text and teh typesetter shoud make both
visulay the sam size not teh sma efont number"*.

## What a point size actually promises

Nothing you can see. A point size is the em - the design grid a face is drawn
on - and how much of that grid the letters fill is the type designer's choice,
not a standard. Measured off the faces this app ships, capital H as a fraction
of the size asked for::

    Anton            0.86        Comic Neue Bold  0.69
    Bangers          0.72        Kalam            0.66
    Jua              0.70        Gaegu            0.62
    Chewy            0.70        Nanum Pen Script 0.56

Anton's capitals are **half again** the height of Nanum Pen Script's at the
same number. So the size box was not a size box: it named a grid, and every
face put a different amount of ink on it. Set a chapter's asides in Nanum Pen
at the size the bubbles use and they come out visibly small; swap one box to
Anton and it shouts without anybody asking it to. The fitter is no help,
because the fitter is measuring the same wrong thing - it fills the balloon
either way, just with letters of the wrong height.

## The conversion, in one place

`typeset.cap_ratio` measures capital H once per file and caches it;
`typeset.px_for` divides it out against `CAP_REF`; and `typeset._font` - the
one function in the app that opens a face for typesetting - is the only caller
that matters. Nothing above it changes. Sizes are still stored, shown, fitted,
searched and saved as the nominal number, so every chapter on disk keeps its
settings and the size box still says what it always said.

`CAP_REF` is 0.69, Comic Neue Bold's own ratio, chosen so that the default
face is the one that does not move. A chapter already typeset in the default
comes out pixel for pixel where it was.

Out of range is DON'T SCALE THIS ONE. A ratio under 0.30 or over 1.20 is not a
type designer's choice, it is a file we failed to read - and a symbol font or a
face with no capital at all would otherwise be multiplied into nonsense.

## And the same conversion in the browser

The preview draws the text itself, in the browser's own font engine, so the
server converting alone would have made the two disagree about every block -
which is worse than both being wrong together. `editor.fonts_answer` ships the
measured ratios as `caps` with the reference as `cap_ref`, `takeFonts` keeps
them, and `project.emPx` is the same sum. Every site that sets a font size or
measures a line goes through it: two in `frames.js` (the two canvases that
measure) and two in `typesetting.js` (the drawn line and the editor).

**The line pitch does not go through it.** `typeset` sets `line_h = size *
leading` on the NOMINAL size, so a browser that converted the pitch too would
have put its lines where the page's lines are not. This is the one asymmetry
in the change and the tests below pin it.

## And the specimens

The font picker rendered every specimen at a flat 30, which is the same bug
one layer up: a list of faces that looked like a list of sizes. It asks
`px_for` now, so the word in the menu is the size the word will come out.
"""
import io
import os
import re

import pytest

from mangatl import typeset as T                            # noqa: E402


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(HERE, "static", "js")


def shipped_faces():
    """Every face in `fonts/`, by path."""
    d = os.path.join(HERE, "fonts")
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, n) for n in os.listdir(d)
                  if n.lower().endswith((".ttf", ".otf")))


def js(name):
    with open(os.path.join(JS, name), encoding="utf-8") as f:
        return f.read()


def code_only(src):
    """The source with its comments and strings taken out.

    A guard that reads source must read the SOURCE. Every rule below is about
    what the code DOES, and this file's own prose - which quotes the very
    patterns being banned - would satisfy or break most of them by accident.
    """
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", " ", src, flags=re.M)
    return src


# ------------------------------------------------- what a ratio may be

def test_every_shipped_face_measures_a_believable_cap_height():
    faces = shipped_faces()
    assert faces, "no fonts to measure - the app ships some"
    for p in faces:
        r = T.cap_ratio(p)
        assert 0.40 <= r <= 1.00, (os.path.basename(p), r)


def test_the_faces_really_do_disagree():
    """The premise. If they all measured the same there is nothing to fix."""
    got = {os.path.basename(p): T.cap_ratio(p) for p in shipped_faces()}
    assert got, got
    lo, hi = min(got.values()), max(got.values())
    assert hi - lo > 0.10, ("all one height - re-read the premise", got)


def test_a_face_we_cannot_read_is_left_alone():
    """Not scaled to nothing, and not an exception either."""
    assert T.cap_ratio(os.path.join(HERE, "no-such-font.ttf")) == T.CAP_REF
    assert T.cap_ratio(os.path.join(HERE, "README.md")) == T.CAP_REF


def test_the_reference_is_the_default_face_so_old_chapters_do_not_move():
    d = T.DEFAULT_FONTS.get("bubble", "")
    p = T.font_file(d) if hasattr(T, "font_file") else None
    if not p or not os.path.exists(p):
        cands = [f for f in shipped_faces()
                 if "comicneue" in os.path.basename(f).lower().replace("-", "")
                 and "bold" in os.path.basename(f).lower()]
        p = cands[0] if cands else None
    if not p:
        pytest.skip("Comic Neue Bold is not on this machine")
    assert abs(T.cap_ratio(p) - T.CAP_REF) < 0.02, T.cap_ratio(p)
    # ...which is to say: the default face asks for exactly the size it is
    # given, so nothing already typeset in it shifts by a pixel.
    for s in (12, 30, 72, 144):
        assert T.px_for(p, s) == s, (s, T.px_for(p, s))


# ------------------------------------------------- what the conversion does

def test_the_same_number_now_draws_the_same_height():
    """The whole point, measured in pixels off the real faces."""
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    from PIL import Image

    heights = {}
    for p in shipped_faces():
        f = T._font(p, 40)
        box = f.getbbox("H")
        heights[os.path.basename(p)] = box[3] - box[1]
    assert heights, heights
    lo, hi = min(heights.values()), max(heights.values())
    assert hi - lo <= 3, ("caps still all over the place", heights)
    # ...and the height is the one the reference promises.
    for n, h in heights.items():
        assert abs(h - 40 * T.CAP_REF) <= 2, (n, h)
    del ImageDraw, Image


def test_without_the_conversion_they_were_all_over_the_place():
    """The before picture, so a regression cannot pass by measuring nothing."""
    from PIL import ImageFont
    heights = {}
    for p in shipped_faces():
        box = ImageFont.truetype(p, 40).getbbox("H")
        heights[os.path.basename(p)] = box[3] - box[1]
    lo, hi = min(heights.values()), max(heights.values())
    assert hi - lo >= 5, ("nothing to fix on this machine?", heights)


def test_a_size_is_still_a_whole_number_of_pixels_and_never_zero():
    for p in shipped_faces():
        for s in (1, 2, 7, 200):
            v = T.px_for(p, s)
            assert isinstance(v, int) and v >= 1, (p, s, v)


def test_nonsense_in_the_size_box_does_not_raise():
    p = shipped_faces()[0]
    for bad in (None, "", "big", float("nan")):
        assert T.px_for(p, bad) >= 1


def test_the_conversion_is_monotonic():
    """Asking for more never gets you less, whatever the face."""
    for p in shipped_faces():
        got = [T.px_for(p, s) for s in range(8, 200, 7)]
        assert got == sorted(got), (p, got)


# ------------------------------------------------- one place, not several

def test_font_is_the_only_place_a_face_is_opened_for_typesetting():
    """One rule, one place. Two copies agree until one changes."""
    import ast
    bad = []
    for name in ("typeset.py", "render.py"):
        path = os.path.join(HERE, name)
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr == "truetype"):
                bad.append((name, node.lineno))
    # `typeset` has exactly three: the openable probe, `cap_ratio`'s own
    # measurement, and `_font` itself (twice, for the face and its spare).
    assert all(n == "typeset.py" for n, _ in bad), bad
    assert len(bad) <= 4, bad


def test_the_picker_specimens_go_through_the_same_sum():
    src = open(os.path.join(HERE, "editor.py"), encoding="utf-8").read()
    src = re.sub(r'""".*?"""', " ", src, flags=re.S)
    src = re.sub(r"^\s*#.*$", " ", src, flags=re.M)
    m = re.search(r"def _font_sample_png\(.*?\n(?=\S)", src, flags=re.S)
    assert m, "the specimen renderer moved"
    body = m.group(0)
    assert "truetype" in body
    assert "px_for" in body, "a specimen list that is really a size list"


# ------------------------------------------------- and the same in the browser

def test_the_server_hands_the_browser_the_measurements():
    from mangatl import editor as E
    ans = E.fonts_answer()
    assert "caps" in ans and "cap_ref" in ans, sorted(ans)
    assert float(ans["cap_ref"]) == T.CAP_REF
    assert ans["caps"], "measured nothing"
    for p, r in ans["caps"].items():
        assert 0.30 <= float(r) <= 1.20, (p, r)


def test_one_answer_still_carries_every_key():
    """`takeFonts` takes what it is handed - a half answer is a wrong page."""
    from mangatl import editor as E
    ans = E.fonts_answer()
    for k in ("fonts", "recent", "uploaded", "defaults",
              "caps", "cap_ref", "marks"):
        assert k in ans, (k, sorted(ans))


def test_the_browser_keeps_what_it_is_handed():
    src = code_only(js("project.js"))
    assert "FONT_CAPS=f.caps" in src.replace(" ", "")
    assert "cap_ref" in src
    assert "function emPx(" in src
    assert "function capOfFam(" in src
    assert "function capFor(" in src


def test_the_browsers_sum_is_the_servers_sum():
    """`size * CAP_REF / cap`, both sides, or the preview lies."""
    src = code_only(js("project.js"))
    m = re.search(r"function emPx\(size, fam\)\{(.*?)\n\}", src, flags=re.S)
    assert m, "emPx moved"
    body = m.group(1).replace(" ", "")
    assert "s*CAP_REF/capOfFam(fam)" in body, body
    py = re.search(r"def px_for\(.*?\n(?=\S)",
                   open(os.path.join(HERE, "typeset.py"), encoding="utf-8")
                   .read(), flags=re.S).group(0)
    assert "size * CAP_REF / cap_ratio(path)" in py


def test_the_browser_clamps_the_same_way_the_server_does():
    src = code_only(js("project.js"))
    m = re.search(r"function capFor\(path\)\{(.*?)\n\}", src, flags=re.S)
    assert m
    body = m.group(1).replace(" ", "")
    assert "0.30" in body and "1.20" in body, body
    assert "CAP_REF" in body, "an unreadable face must be LEFT ALONE"


def test_every_place_the_browser_sets_a_font_size_converts_it():
    """The four sites, and a guard against a fifth appearing unconverted."""
    seen = 0
    for name in ("frames.js", "typesetting.js", "panels.js", "view.js",
                 "project-io.js", "picker.js", "typesetting-edit.js"):
        src = code_only(js(name))
        for m in re.finditer(r"(?:\.font\s*=\s*`|font-size:\$\{|fontSize\s*=)"
                             r"[^;`\n]*", src):
            frag = m.group(0)
            if "px" not in frag and "${" not in frag:
                continue
            seen += 1
            assert "emPx(" in frag, (name, frag.strip())
    assert seen >= 4, ("the drawing sites moved", seen)


def test_the_family_can_be_traced_back_to_its_file():
    """`emPx` is handed a family name; the cap height is keyed by path."""
    fam = code_only(js("typesetting.js"))
    assert "FAM_PATH[fam]=path" in fam.replace(" ", ""), \
        "fontFam stopped recording which file a family came from"
    src = code_only(js("project.js"))
    assert "let FAM_PATH" in src
    # ...and the kind fallback face is resolved LIVE, because which file
    # `ml-bubble` means depends on settings that change while the page is open.
    m = re.search(r"function capOfFam\(fam\)\{(.*?)\n\}", src, flags=re.S)
    assert m and "fontPathFor(" in m.group(1), m and m.group(1)


def test_the_line_pitch_is_not_converted():
    """The one asymmetry, and the reason for it.

    `typeset` spaces lines at `size * leading` on the nominal size. A browser
    that converted the pitch as well would draw its lines somewhere the
    exported page does not.
    """
    for name in ("frames.js", "typesetting.js"):
        src = code_only(js(name))
        for m in re.finditer(r"(?:lh|lineHeight)\s*=[^;\n]*", src):
            assert "emPx(" not in m.group(0), (name, m.group(0))
    # ...and it is still the nominal size doing the spacing.
    assert "L.font_size*(L.leading" in code_only(js("frames.js")).replace(" ", "")


def test_the_size_box_still_shows_the_number_that_was_stored():
    """Converted for drawing, never for keeping. Every chapter on disk keeps
    the sizes it was saved with, and the panel says what they are."""
    src = code_only(js("frames.js"))
    m = re.search(r"sz\.value\s*=\s*([^;\n]+)", src)
    assert m, "the size box moved"
    assert "emPx" not in m.group(1), m.group(1)
    assert "font_size" in m.group(1), m.group(1)
