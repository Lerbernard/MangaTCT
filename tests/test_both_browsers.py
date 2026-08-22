"""The app has to look and behave the same in Chrome and in Firefox.

lee: *"the website need to fully work the same on chrome and on firefox"*.

Only Chromium is installed here, so the browser-by-browser half of this cannot
be run - what CAN be checked, and is checked below, is that the app never
relies on one browser's mechanism without providing the other's. Every place
the two engines diverge is a place this app has already been bitten:

* the number spinner - Chromium's can be painted, Firefox's cannot be touched,
  so both are switched off and one is built out of buttons
* the range slider - `::-webkit-slider-thumb` and `::-moz-range-thumb` are
  different pseudo-elements and neither browser understands the other's
* the scrollbar - Firefox takes two properties, Chromium a set of
  pseudo-elements, and with neither given each drew its own pale native bar
* a `change` event on a focused element that gets removed - Chromium fires it,
  Firefox does not

A rule the CSS depends on: **a selector list containing one selector the
browser does not understand is thrown away whole.** So a webkit and a moz
pseudo-element can never share a rule, and a file that does that silently loses
the styling in both. That is worth a test of its own.
"""
import re

import pytest
from where import PKG

CSS = (PKG / "static" / "css" / "editor.css").read_text("utf8")
JS_DIR = PKG / "static" / "js"


def _rules():
    """(selectors, body) for every rule in the sheet, comments stripped."""
    clean = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", clean)]


def test_no_rule_mixes_a_webkit_and_a_moz_selector():
    """One selector the browser cannot parse throws the whole list away, so a
    rule naming both is a rule that works in neither."""
    bad = []
    for sel, _ in _rules():
        if "-webkit-" in sel and "-moz-" in sel:
            bad.append(sel)
    assert bad == [], bad


def test_the_slider_knob_answers_the_same_in_both():
    """Hover, active and focus were painted for Chromium's thumb and for
    nothing else, so the same knob behaved differently depending on the
    browser."""
    for state in (":hover", ":active", ":focus-visible"):
        webkit = [s for s, _ in _rules()
                  if state in s and "-webkit-slider-thumb" in s]
        moz = [s for s, _ in _rules()
               if state in s and "-moz-range-thumb" in s]
        assert bool(webkit) == bool(moz), (state, webkit, moz)


def test_the_slider_track_is_drawn_for_both():
    flat = CSS.replace(" ", "")
    assert "::-webkit-slider-runnable-track" in flat
    assert "::-moz-range-track" in flat


def test_the_scrollbars_are_described_for_both():
    flat = CSS.replace(" ", "")
    # Chromium: pseudo-elements. Track, corner and the stepper arrows matter as
    # much as the thumb - leave any of them out and a pale native part shows.
    for part in ("::-webkit-scrollbar{", "::-webkit-scrollbar-thumb{",
                 "::-webkit-scrollbar-track{", "::-webkit-scrollbar-corner{",
                 "::-webkit-scrollbar-button{"):
        assert part in flat, part
    # Firefox: two plain properties.
    assert "scrollbar-width:thin" in flat, "Firefox draws its own"
    assert "scrollbar-color:" in flat, "Firefox draws its own"


def test_the_two_scrollbar_mechanisms_are_never_given_to_the_same_browser():
    """They are not additive, they FIGHT. From Chromium 121 the standard
    `scrollbar-color` wins and the whole `::-webkit-scrollbar` set is dropped -
    so giving both to everybody is exactly what put the pale native bar back in
    Chrome. Firefox's half has to be fenced behind a test for the thing only
    Chromium has.
    """
    clean = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    at = clean.find("scrollbar-color")
    assert at > 0, "Firefox is not given a scrollbar at all"
    fence = clean.rfind("@supports", 0, at)
    assert fence > 0, "scrollbar-color is set unconditionally"
    head = clean[fence:clean.index("{", fence)]
    assert "not" in head and "::-webkit-scrollbar" in head, head
    assert "scrollbar-width" not in clean[:fence], \
        "scrollbar-width is set outside the fence too"


def test_neither_native_number_spinner_is_left_on():
    flat = CSS.replace(" ", "")
    bare = flat[flat.index("input[type=number]{"):][:200]
    assert "-moz-appearance:textfield" in bare
    spin = flat[flat.index("::-webkit-inner-spin-button"):]
    assert "display:none" in spin[:spin.index("}")]


def test_nothing_reaches_for_a_chromium_only_javascript_api():
    """`webkitRequestAnimationFrame`, `webkitMatchesSelector` and friends do
    not exist in Firefox, and neither does `document.all`."""
    banned = ("webkitRequestAnimationFrame", "webkitMatchesSelector",
              "webkitURL", "document.all", "window.chrome",
              "webkitAudioContext", "mozRequestAnimationFrame")
    found = []
    for f in sorted(JS_DIR.glob("*.js")):
        src = f.read_text("utf8")
        for b in banned:
            if b in src:
                found.append((f.name, b))
    assert found == [], found


def test_requestanimationframe_is_never_assumed():
    """The UI tests run in jsdom, which has no rAF, and a bare call there
    throws - inside a MutationObserver callback nothing catches it, so the
    console fills and whatever came after the call never happens.

    There is one guarded helper, `soon`, in core.js. Everything else uses it.
    """
    import re as _re
    for f in sorted(JS_DIR.glob("*.js")):
        src = _re.sub(r"/\*.*?\*/", "", f.read_text("utf8"), flags=_re.S)
        src = "\n".join(l for l in src.splitlines()
                        if not l.strip().startswith("//"))
        for line in src.splitlines():
            if "requestAnimationFrame" not in line:
                continue
            assert ("typeof requestAnimationFrame" in line
                    or "? (f)=>requestAnimationFrame(f)" in line), \
                (f.name, line.strip(), "use soon() from core.js")
    assert "const soon =" in (JS_DIR / "core.js").read_text("utf8")


def test_a_field_is_never_trusted_to_report_itself_on_removal():
    """The divergence that has cost this app the most: Firefox does not fire
    `change` on an element removed while it still has focus, and Chromium does.
    Both lists in the panel are rebuilt constantly, so nothing may depend on
    that event - there is a flush before every rebuild instead."""
    panels = (JS_DIR / "panels.js").read_text("utf8")
    assert "flushTypesetEdit()" in panels, "the typesetting panel has no flush"
    # renderList flushes the list, renderInspector flushes the typesetting
    head = panels[panels.index("function renderInspector(){"):][:900]
    assert "flushTypesetEdit" in head
    head = panels[panels.index("function renderList(){"):][:900]
    assert "flushEdit" in head


def test_the_stepper_does_not_depend_on_one_release_event():
    """A repeat that only stops on `mouseup` runs for ever if that one event is
    missed - the pointer leaving the window, a context menu, the tab being
    switched. Every browser loses a different one of those."""
    src = (JS_DIR / "project-io.js").read_text("utf8")
    for ev in ("mouseup", "pointerup", "pointercancel", "blur",
               "visibilitychange"):
        assert ev in src, ev
    assert "left <= 0" in src or "left<=0" in src, "the repeat has no cap"


def test_the_release_is_listened_for_in_the_capture_phase():
    """This is the whole bug, and it is not browser-specific - it just bit in
    Chrome first.

    The paint tools and the frame handles call `stopPropagation()` on the way
    up, so a `mouseup` listener on `window` in the BUBBLE phase never runs when
    the pointer is anywhere near the page. The stepper's repeat is stopped by
    that listener. Miss it once and the repeat runs for ever, saving on every
    step, and the app stops answering - lee: *"the page is froxoen and teh
    image is not chnaging"*.

    Capture runs first and cannot be cancelled by anything downstream.
    """
    src = (JS_DIR / "project-io.js").read_text("utf8")
    add = [l for l in src.splitlines() if "addEventListener(n, release" in l]
    rm = [l for l in src.splitlines() if "removeEventListener(n, release" in l]
    assert add and all(l.rstrip().endswith("true));") for l in add), add
    assert rm and all(l.rstrip().endswith("true));") for l in rm), rm
