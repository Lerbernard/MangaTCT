"""Every script the editor loads has to be valid JavaScript.

This exists because of one edit. A helper was inserted immediately before
`function saveSettings(`, and the real line was::

    async function saveSettings(){

so the insert landed between the `async` and the `function` and left::

    async /* comment */
    function syncFindAi(){ ... }

    function saveSettings(){ ... await ... }

`saveSettings` stopped being async while still containing `await`, which is a
SYNTAX error -- so the whole file failed to parse, `loadProject` was never
defined, and the editor did not boot at all. Not the settings page: the editor.

Fifteen browser tests caught it, and every one of them caught it as a
thirty-second Playwright timeout with no error in it, five minutes of suite
time to find out that a file would not parse. A parse check costs
milliseconds and says which file and which line.

Classic scripts, no build step, no bundler -- nothing else in this project ever
reads these files as code before a browser does.
"""
import shutil
import subprocess

import pytest

from where import PKG

JS = sorted((PKG / "static" / "js").glob("*.js"))
NODE = shutil.which("node")


def test_there_are_scripts_to_check():
    """A glob that matches nothing passes every test below it."""
    assert len(JS) > 10, [p.name for p in JS]


@pytest.mark.skipif(not NODE, reason="node is not installed here")
@pytest.mark.parametrize("path", JS, ids=lambda p: p.name)
def test_the_script_parses(path):
    got = subprocess.run([NODE, "--check", str(path)],
                         capture_output=True, text=True)
    assert got.returncode == 0, got.stderr.strip()[:600]


@pytest.mark.skipif(not NODE, reason="node is not installed here")
def test_the_page_loads_every_one_of_them():
    """A file that parses but is never loaded is not checked by anything, and
    a file loaded but not on disk is a 404 the browser shrugs at. The list in
    the HTML and the files in the folder have to be the same list.

    Order matters and is not checked here -- these are classic scripts sharing
    one global scope and the HTML is the only place that says which order.
    """
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    loaded = {p.name for p in JS if f"/static/js/{p.name}" in html}
    assert loaded == {p.name for p in JS}, \
        sorted({p.name for p in JS} - loaded)
