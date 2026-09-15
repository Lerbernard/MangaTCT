"""Browse, Save as and Open ask the app's window for its dialog.

lee, with a crop of the Export dialog's Browse... button: *"thsi brows button
donst work"*.

All three used to ask the editor's server, which starts a separate Python
process to show a Tk dialog (`pickdir.py`). That window belongs to nothing on
screen, so where it lands in the stacking order is up to Windows, and a person
looking at the app sees nothing happen while the button waits. In the app's
window the dialog now comes from the window itself (`Api.pick_dir`,
`Api.pick_project`), modal to it; a browser tab, or a window that could not
ask, still gets the server's.
"""
import os

import pytest

from where import PKG


class FakeWindow:
    def __init__(self, answer=None, boom=False):
        self.answer, self.boom, self.asked = answer, boom, []

    def create_file_dialog(self, kind, **kw):
        self.asked.append((kind, kw))
        if self.boom:
            raise RuntimeError("no dialog here")
        return self.answer


def _api(win):
    from mangatl import window as W
    api = W.Api()
    api._win = win
    return api


def test_a_folder_comes_back_from_the_window(tmp_path):
    win = FakeWindow(answer=(str(tmp_path),))
    assert _api(win).pick_dir(str(tmp_path)) == str(tmp_path)
    kind, kw = win.asked[0]
    assert kind in (20,) or "FOLDER" in str(kind).upper(), kind
    assert kw["directory"] == str(tmp_path)


def test_cancelled_is_empty_and_could_not_ask_is_none(tmp_path):
    assert _api(FakeWindow(answer=None)).pick_dir(str(tmp_path)) == ""
    assert _api(FakeWindow(boom=True)).pick_dir(str(tmp_path)) is None
    assert _api(None).pick_dir(str(tmp_path)) is None


def test_save_as_gets_the_extension_and_open_needs_a_real_file(tmp_path):
    saved = _api(FakeWindow(answer=str(tmp_path / "chapter 3"))).pick_project(
        str(tmp_path), save=True)
    assert saved == str(tmp_path / "chapter 3") + ".tctp"
    real = tmp_path / "ch.tctp"
    real.write_bytes(b"x")
    assert _api(FakeWindow(answer=(str(real),))).pick_project(str(tmp_path)) == str(real)
    assert _api(FakeWindow(answer=(str(tmp_path / "gone.tctp"),))).pick_project(
        str(tmp_path)) == ""


def test_a_start_that_is_a_file_opens_in_its_folder(tmp_path):
    f = tmp_path / "old.tctp"
    f.write_bytes(b"x")
    win = FakeWindow(answer=None)
    _api(win).pick_project(str(f), save=True)
    kind, kw = win.asked[0]
    assert kw["directory"] == str(tmp_path)
    assert kw["save_filename"] == "old.tctp"


def test_the_page_asks_the_window_first_and_the_server_after():
    js = (PKG / "static" / "js" / "project-io.js").read_text("utf-8")
    body = js[js.index("async function pickPath("):js.index("async function browseDir(")]
    assert body.index("w.pick_dir") < body.index("/api/pick_dir"), body
    assert body.index("w.pick_project") < body.index("/api/pick_project"), body
    assert "p !== null" in body, "a window that could not ask must fall back"
    browse = js[js.index("async function browseDir("):]
    browse = browse[:browse.index("\n}")]
    assert "pickPath('dir'" in browse and "/api/pick_dir" not in browse, browse
    for fn in ("async function saveProjectAs(", "async function openProject("):
        seg = js[js.index(fn):]
        seg = seg[:seg.index("\n}")]
        assert "pickPath(" in seg and "/api/pick_project" not in seg, fn
