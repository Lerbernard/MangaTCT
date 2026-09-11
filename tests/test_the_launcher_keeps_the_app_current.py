"""The Windows launcher: fetches a newer app, never breaks the one running.

lee: *"lets go with teh doenload option, i still want to be able to send out
update and keep suporting teh app"*.

`launcher/mangatct_launcher.py` is frozen into `MangaTCT.exe`. It is plain
Python and every decision it makes is exercised here on Linux: a release
channel served from a local HTTP server, a runtime that is a shell script
standing in for `python.exe`, and an app that is a stub `mangatl.editor`
answering `/api/version`. What is NOT tested here is tkinter and Windows -
the release job builds the exe on a Windows runner and lee runs the
installer.
"""
import hashlib
import http.server
import io
import json
import os
import shutil
import socket
import stat
import sys
import threading
import time
import zipfile

import pytest

from where import PKG

sys.path.insert(0, str(PKG / "launcher"))
import mangatct_launcher as L  # noqa: E402


# ------------------------------------------------------------------ fixtures

STUB_EDITOR = '''
import argparse, json, sys, os
from http.server import BaseHTTPRequestHandler, HTTPServer
ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int); ap.add_argument("--no-browser", action="store_true"); ap.add_argument("--output", default="")
a = ap.parse_args()
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"version": VERSION, "weights": os.environ.get("MANGATL_WEIGHTS", ""), "update_file": os.environ.get("MANGATL_UPDATE_FILE", ""), "output": a.output}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *x): pass
print("stub editor", VERSION, "on", a.port, flush=True)
HTTPServer(("127.0.0.1", a.port), H).serve_forever()
'''


def app_zip(version: str, requirements: str = "numpy\n") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mangatl/__init__.py", "")
        z.writestr("mangatl/editor.py", "VERSION = %r\n" % version + STUB_EDITOR)
        z.writestr("mangatl/version.py", "__version__ = %r\n" % version)
        z.writestr("requirements.txt", requirements)
    return buf.getvalue()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Channel:
    """A release channel on localhost: a manifest and the files it names."""

    def __init__(self):
        self.files = {}
        self.hits = []
        self.no_range = False
        chan = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                chan.hits.append(self.path)
                body = chan.files.get(self.path)
                if body is None:
                    self.send_response(404); self.end_headers(); return
                rng = self.headers.get("Range")
                if rng and not chan.no_range:
                    start = int(rng.split("=")[1].split("-")[0])
                    part = body[start:]
                    self.send_response(206)
                    self.send_header("Content-Range", "bytes %d-%d/%d" % (start, len(body) - 1, len(body)))
                else:
                    part = body
                    self.send_response(200)
                self.send_header("Content-Length", str(len(part)))
                self.end_headers()
                self.wfile.write(part)

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def publish(self, version, requirements="numpy\n", **extra):
        z = app_zip(version, requirements)
        self.files["/mangatct-app-%s.zip" % version] = z
        man = {"app": {"version": version, "url": self.url("/mangatct-app-%s.zip" % version),
                       "sha256": sha(z), "size": len(z), "notes": "https://notes/" + version},
               **extra}
        self.files["/manifest.json"] = json.dumps(man).encode()
        return man

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def channel():
    c = Channel()
    yield c
    c.close()


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A MangaTCT home with a runtime that is a shell script: `pip` calls
    are recorded and succeed unless a PIP_FAILS file exists; anything else
    runs on the real interpreter."""
    root = tmp_path / "MangaTCT"
    p = L.paths(str(root))
    L.ensure_dirs(p)
    os.makedirs(os.path.dirname(p["python"]), exist_ok=True)
    with open(p["python"], "w") as f:
        f.write("#!/bin/sh\n"
                "case \"$*\" in *'-m pip'*) echo \"$@\" >> '%s'; "
                "[ -f '%s' ] && exit 1; exit 0;; esac\n"
                "exec '%s' \"$@\"\n" % (root / "pip.log", root / "PIP_FAILS", sys.executable))
    os.chmod(p["python"], os.stat(p["python"]).st_mode | stat.S_IEXEC)
    monkeypatch.setenv("MANGATCT_HOME", str(root))
    monkeypatch.setattr(L, "EDITOR_WAIT", 30.0)
    return p


def install(p, version, requirements="numpy\n"):
    z = app_zip(version, requirements)
    fp = os.path.join(p["app"], "x.zip")
    with open(fp, "wb") as f:
        f.write(z)
    assert L.install_app_zip(p, fp, version)
    os.remove(fp)


# ------------------------------------------------------------ the versions

def test_only_complete_versions_count(home):
    p = home
    install(p, "1.0.0")
    os.makedirs(os.path.join(p["app"], "1.0.1", "mangatl"))        # no .complete
    os.makedirs(os.path.join(p["app"], "1.0.2.tmp", "mangatl"))    # a crash's leftovers
    with open(os.path.join(p["app"], "1.0.2.tmp", ".complete"), "w"):
        pass
    assert L.installed_versions(p) == ["1.0.0"]
    install(p, "1.0.10")
    install(p, "1.0.9")
    assert L.installed_versions(p) == ["1.0.10", "1.0.9", "1.0.0"], "as numbers"


def test_a_zip_that_would_write_outside_its_folder_is_refused(home):
    p = home
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mangatl/__init__.py", "")
        z.writestr("../evil.txt", "x")
    fp = os.path.join(p["app"], "bad.zip")
    with open(fp, "wb") as f:
        f.write(buf.getvalue())
    assert not L.install_app_zip(p, fp, "2.0.0")
    assert not os.path.exists(os.path.join(p["app"], "evil.txt"))
    assert L.installed_versions(p) == []


# ------------------------------------------------------------- the download

def test_a_download_is_kept_only_if_the_checksum_matches(home, channel, tmp_path):
    body = b"x" * 100_000
    channel.files["/f.bin"] = body
    dest = str(tmp_path / "f.bin")
    assert not L.download(channel.url("/f.bin"), dest, "deadbeef")
    assert not os.path.exists(dest) and not os.path.exists(dest + ".part")
    assert L.download(channel.url("/f.bin"), dest, sha(body), len(body))
    assert open(dest, "rb").read() == body


def test_a_download_resumes_where_the_lid_closed(home, channel, tmp_path):
    body = bytes(range(256)) * 1000
    channel.files["/f.bin"] = body
    dest = str(tmp_path / "f.bin")
    with open(dest + ".part", "wb") as f:
        f.write(body[:100_000])
    seen = []
    assert L.download(channel.url("/f.bin"), dest, sha(body), len(body),
                      progress=lambda d, t: seen.append((d, t)))
    assert open(dest, "rb").read() == body
    assert seen[0][0] >= 100_000, "counted from where it left off"
    # ...and starts over when the server will not do ranges
    channel.no_range = True
    with open(dest + ".part", "wb") as f:
        f.write(body[:100_000])
    assert L.download(channel.url("/f.bin"), dest, sha(body), len(body))
    assert open(dest, "rb").read() == body


# ---------------------------------------------------------------- the check

def test_a_newer_version_is_fetched_beside_the_current_one(home, channel):
    p = home
    install(p, "1.0.0")
    man = channel.publish("1.0.1")
    got = L.check_for_update(p, man)
    assert got == "1.0.1"
    assert L.installed_versions(p) == ["1.0.1", "1.0.0"], "the old one is still there"
    assert L.read_json(p["update"], {}) == {"available": "1.0.1", "state": "ready",
                                           "notes": "https://notes/1.0.1"}
    assert not os.path.exists(os.path.join(p["app"], "mangatct-app-1.0.1.zip"))


def test_the_channel_being_older_or_equal_fetches_nothing(home, channel):
    p = home
    install(p, "1.0.1")
    assert L.check_for_update(p, channel.publish("1.0.1")) is None
    assert L.check_for_update(p, channel.publish("0.9.0")) is None
    assert L.check_for_update(p, None) is None, "offline is not an event"
    assert not any("zip" in h for h in channel.hits)
    assert not os.path.exists(p["update"])


def test_a_bad_checksum_on_the_channel_changes_nothing(home, channel):
    p = home
    install(p, "1.0.0")
    man = channel.publish("1.0.1")
    man["app"]["sha256"] = "0" * 64
    assert L.check_for_update(p, man) is None
    assert L.installed_versions(p) == ["1.0.0"]
    assert not os.path.exists(p["update"]), "no promise the next start cannot keep"


def test_old_versions_are_pruned_but_never_the_running_one(home):
    p = home
    for v in ("1.0.0", "1.0.1", "1.0.2", "1.0.3"):
        install(p, v)
    os.makedirs(os.path.join(p["app"], "1.0.4.tmp"))
    L.prune_old(p, "1.0.3")
    assert L.installed_versions(p) == ["1.0.3", "1.0.2"]
    assert not os.path.exists(os.path.join(p["app"], "1.0.4.tmp"))
    # running an OLD one on purpose (a fallback) keeps it too
    install(p, "1.0.5")
    L.prune_old(p, "1.0.2")
    assert set(L.installed_versions(p)) == {"1.0.5", "1.0.2"}


# ---------------------------------------------------------------- the pip

def test_pip_runs_only_when_the_requirements_changed(home):
    p = home
    install(p, "1.0.0", "numpy\n")
    d = L.app_dir(p, "1.0.0")
    assert L.pip_sync(p, d)
    piplog = os.path.join(p["root"], "pip.log")
    assert open(piplog).read().count("install") == 1
    assert L.pip_sync(p, d), "same requirements"
    assert open(piplog).read().count("install") == 1, "no second pip"
    install(p, "1.0.1", "numpy\npillow\n")
    assert L.pip_sync(p, L.app_dir(p, "1.0.1"))
    assert open(piplog).read().count("install") == 2


def test_a_version_whose_packages_cannot_be_installed_falls_back(home):
    p = home
    install(p, "1.0.0", "numpy\n")
    assert L.pip_sync(p, L.app_dir(p, "1.0.0"))
    install(p, "1.0.1", "numpy\nsomething-new\n")
    open(os.path.join(p["root"], "PIP_FAILS"), "w").close()
    v, fell_back, err = L.choose_and_prepare(p)
    assert (v, fell_back, err) == ("1.0.0", True, "")


def test_no_runtime_or_no_app_is_said_plainly(home):
    p = home
    v, _, err = L.choose_and_prepare(p)
    assert v is None and "No version of the app" in err
    os.remove(p["python"])
    v, _, err = L.choose_and_prepare(p)
    assert v is None and "runtime is missing" in err


# -------------------------------------------------------------- the start

def test_a_start_fetches_the_update_and_runs_it(home, channel):
    """Nothing is open yet when the start looks at the channel, so a version
    fetched then is the version started - the fix arrives now, not next
    time. The pill has nothing to say, because nothing is waiting."""
    p = home
    install(p, "1.0.0")
    channel.publish("1.0.1")
    told = []
    s = L.run(p, manifest_url=channel.url("/manifest.json"), progress=told.append,
              open_browser=False)
    try:
        assert s.proc and s.port, s.error
        assert s.version == "1.0.1" and s.fetched == "1.0.1"
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:%d/api/version" % s.port) as r:
            got = json.load(r)
        assert got["version"] == "1.0.1"
        assert got["weights"] == p["models"], "MANGATL_WEIGHTS points at the models folder"
        assert got["update_file"] == p["update"]
        assert got["output"].endswith(os.path.join("MangaTCT", "out"))
        assert not os.path.exists(p["update"]), "nothing waiting"
        assert L.installed_versions(p) == ["1.0.1", "1.0.0"], "the old one kept, for undo"
        assert any("Checking" in t for t in told) and any("Starting" in t for t in told)
        assert any("Downloading" in t for t in told)
    finally:
        L.stop_editor(s.proc)
    assert L.read_state(p)["app"] == "1.0.1"


def test_a_version_fetched_while_the_editor_runs_waits_for_the_next_start(home, channel):
    """The mid-session check puts the new version beside the running one and
    tells the pill; the switch is the next start's."""
    p = home
    install(p, "1.0.0")
    channel.publish("1.0.0")
    s = L.run(p, manifest_url=channel.url("/manifest.json"), open_browser=False)
    try:
        assert s.version == "1.0.0"
        channel.publish("1.0.1")
        # the watcher's own loop sleeps for hours; call what it calls
        assert L.check_for_update(p, L.fetch_manifest(channel.url("/manifest.json"))) == "1.0.1"
        assert L.read_json(p["update"], {}) == {"available": "1.0.1", "state": "ready",
                                               "notes": "https://notes/1.0.1"}
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:%d/api/version" % s.port) as r:
            assert json.load(r)["version"] == "1.0.0", "still the one that was open"
    finally:
        L.stop_editor(s.proc)
    s2 = L.run(p, manifest_url=channel.url("/manifest.json"), open_browser=False)
    try:
        assert s2.version == "1.0.1" and s2.fetched is None
        assert not os.path.exists(p["update"])
    finally:
        L.stop_editor(s2.proc)


def test_a_fetched_version_that_cannot_be_prepared_is_not_advertised(home, channel):
    p = home
    install(p, "1.0.0", "numpy\n")
    assert L.pip_sync(p, L.app_dir(p, "1.0.0"))
    channel.publish("1.0.1", "numpy\nsomething-new\n")
    open(os.path.join(p["root"], "PIP_FAILS"), "w").close()
    s = L.run(p, manifest_url=channel.url("/manifest.json"), open_browser=False)
    try:
        assert s.version == "1.0.0" and s.fell_back
        assert not os.path.exists(p["update"]), "a pill saying 'ready' would be a lie"
    finally:
        L.stop_editor(s.proc)


def test_offline_starts_what_is_installed(home):
    p = home
    install(p, "1.0.0")
    s = L.run(p, manifest_url="http://127.0.0.1:9/manifest.json", open_browser=False)
    try:
        assert s.proc and s.version == "1.0.0"
    finally:
        L.stop_editor(s.proc)
    log = open(os.path.join(p["logs"], "launcher.log")).read()
    assert "manifest: not reachable" in log
    assert os.path.exists(os.path.join(p["logs"], "editor-%s.log" % time.strftime("%Y-%m-%d")))


def test_an_editor_that_dies_is_reported_not_waited_on(home):
    p = home
    install(p, "1.0.0")
    with open(os.path.join(L.app_dir(p, "1.0.0"), "mangatl", "editor.py"), "w") as f:
        f.write("raise SystemExit('boom')\n")
    t0 = time.time()
    s = L.run(p, manifest_url="http://127.0.0.1:9/m.json", open_browser=False)
    assert s.proc is not None and s.port
    assert "did not start" in s.error
    assert time.time() - t0 < 20


# -------------------------------------------------------------- the models

def _models_json(p, version, models):
    with open(os.path.join(L.app_dir(p, version), "models.json"), "w") as f:
        json.dump({"models": models}, f)


def test_missing_weights_are_fetched_once_and_checked(home, channel):
    p = home
    install(p, "1.0.0")
    w1 = b"weights-one" * 1000
    inner = b"inner-onnx" * 500
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("model.onnx", inner)
    channel.files["/a.onnx"] = w1
    channel.files["/b.zip"] = zbuf.getvalue()
    _models_json(p, "1.0.0", [
        {"name": "a.onnx", "url": channel.url("/a.onnx"), "sha256": sha(w1), "size": len(w1), "tier": "required"},
        {"name": "b.onnx", "url": channel.url("/b.zip"), "inside": "model.onnx", "sha256": sha(inner), "tier": "recommended"},
    ])
    told = []
    assert L.ensure_models(p, L.app_dir(p, "1.0.0"), told.append) == ""
    assert open(os.path.join(p["models"], "a.onnx"), "rb").read() == w1
    assert open(os.path.join(p["models"], "b.onnx"), "rb").read() == inner, "unzipped and renamed"
    assert not os.path.exists(os.path.join(p["models"], "b.onnx.zip"))
    assert any("1 of 2" in t for t in told)
    hits = len(channel.hits)
    assert L.ensure_models(p, L.app_dir(p, "1.0.0")) == ""
    assert len(channel.hits) == hits, "already there: nothing fetched again"


def test_a_required_weight_that_will_not_come_stops_the_start_plainly(home, channel):
    p = home
    install(p, "1.0.0")
    _models_json(p, "1.0.0", [
        {"name": "need.onnx", "url": channel.url("/gone"), "sha256": "00", "tier": "required"},
        {"name": "nice.pt", "url": channel.url("/gone"), "sha256": "00", "tier": "recommended"},
    ])
    err = L.ensure_models(p, L.app_dir(p, "1.0.0"))
    assert "need.onnx could not be downloaded" in err and "127.0.0.1" in err
    s = L.run(p, manifest_url="http://127.0.0.1:9/m.json", open_browser=False)
    assert s.proc is None and "need.onnx" in s.error
    # ...and a recommended one alone is a log line, not a stop
    _models_json(p, "1.0.0", [
        {"name": "nice.pt", "url": channel.url("/gone"), "sha256": "00", "tier": "recommended"}])
    assert L.ensure_models(p, L.app_dir(p, "1.0.0")) == ""


def test_a_weight_that_arrives_different_is_refused(home, channel):
    p = home
    install(p, "1.0.0")
    channel.files["/a.onnx"] = b"tampered"
    _models_json(p, "1.0.0", [
        {"name": "a.onnx", "url": channel.url("/a.onnx"), "sha256": sha(b"the real one"), "tier": "recommended"}])
    assert L.ensure_models(p, L.app_dir(p, "1.0.0")) == ""
    assert not os.path.exists(os.path.join(p["models"], "a.onnx"))


def test_a_weight_is_tried_from_every_address_in_order(home, channel):
    """1.0.3: `urls`, the project's mirror first and the publisher after.
    An installed copy that can reach GitHub but not Hugging Face used to
    start with the AnimeText route gray; now the mirror answers, and when
    the mirror is the one missing, the publisher still does."""
    p = home
    install(p, "1.0.0")
    w = b"weights" * 1000
    inner = b"inner" * 500
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("model.onnx", inner)
    channel.files["/pub/a.pt"] = w
    channel.files["/pub/b.zip"] = zbuf.getvalue()
    _models_json(p, "1.0.0", [
        # the mirror is gone; the publisher has it
        {"name": "a.pt", "url": channel.url("/pub/a.pt"),
         "urls": [{"url": channel.url("/mirror/a.pt")}, {"url": channel.url("/pub/a.pt")}],
         "sha256": sha(w), "size": len(w), "tier": "recommended"},
        # a bare file on the mirror, a zip at the publisher - each said its own way
        {"name": "b.onnx", "url": channel.url("/pub/b.zip"), "inside": "model.onnx",
         "urls": [{"url": channel.url("/mirror/b.onnx")},
                  {"url": channel.url("/pub/b.zip"), "inside": "model.onnx"}],
         "sha256": sha(inner), "size": len(inner), "tier": "recommended"},
    ])
    assert L.ensure_models(p, L.app_dir(p, "1.0.0")) == ""
    assert open(os.path.join(p["models"], "a.pt"), "rb").read() == w
    assert open(os.path.join(p["models"], "b.onnx"), "rb").read() == inner
    assert channel.hits.index("/mirror/a.pt") < channel.hits.index("/pub/a.pt"), "mirror first"
    # ...and with the mirror answering, the publisher is never asked
    channel.files["/mirror/c.pt"] = w
    _models_json(p, "1.0.0", [
        {"name": "c.pt", "url": channel.url("/pub/c.pt"),
         "urls": [{"url": channel.url("/mirror/c.pt")}, {"url": channel.url("/pub/c.pt")}],
         "sha256": sha(w), "size": len(w), "tier": "recommended"}])
    assert L.ensure_models(p, L.app_dir(p, "1.0.0")) == ""
    assert "/pub/c.pt" not in channel.hits
    # an old-style entry - one `url` - is one source
    assert L.model_sources({"url": "https://x/y", "inside": "m"}) == [{"url": "https://x/y", "inside": "m"}]


def test_the_shipped_model_list_is_well_formed():
    """`tools/models.json` is copied into every release zip; the launcher
    reads it. Every entry needs what `fetch_model` needs, and the required
    one is the detector every route cleans with."""
    d = json.loads((PKG / "tools" / "models.json").read_text(encoding="utf-8"))
    names = [m["name"] for m in d["models"]]
    assert "comictextdetector.pt.onnx" in names
    mirror = "https://github.com/Lerbernard/MangaTCT/releases/download/models/"
    for m in d["models"]:
        assert m["url"].startswith("https://"), m["name"]
        assert len(m["sha256"]) == 64, m["name"]
        assert m["tier"] in ("required", "recommended"), m["name"]
        assert m["size"] > 0
        srcs = L.model_sources(m)
        assert all(u["url"].startswith("https://") for u in srcs), m["name"]
        # `url` is the LAST source (the publisher, or the mirror when there
        # is no publisher address) - what a launcher before 1.0.3 reads
        assert srcs[-1]["url"] == m["url"] and srcs[-1]["inside"] == m.get("inside"), m["name"]
        if m["name"].startswith("webtoon-"):
            assert all(mirror not in u["url"] for u in srcs), "licence not written down: not mirrored"
        else:
            assert srcs[0]["url"] == mirror + m["name"], "%s: the project's mirror first" % m["name"]
    req = [m["name"] for m in d["models"] if m["tier"] == "required"]
    assert req == ["comictextdetector.pt.onnx"], "only the one nothing works without"
    assert "dbpp_coo.dat" in names, "the sound-effect weights, which no publisher serves"
    assert "animetext.pt" in names and "m109seg.pt" in names


# --------------------------------------------------------------- the rules

def test_it_is_standard_library_only():
    """Frozen into an exe, and the thing that must work when the runtime it
    installs does not."""
    import ast
    src = (PKG / "launcher" / "mangatct_launcher.py").read_text(encoding="utf-8")
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    allowed = {"datetime", "hashlib", "json", "os", "shutil", "socket", "subprocess",
               "sys", "threading", "time", "urllib", "zipfile", "webbrowser",
               "tkinter", "ctypes", "__future__"}      # ctypes: the dark title bar
    assert mods <= allowed, mods - allowed


def test_the_channel_is_one_https_file_on_the_projects_own_repo():
    """lee: *"we alredy have a github repo, we dont need a newone"*. One
    file, fetched without a token, which is why the repository has to be
    public - and it is GPL-3.0, so its source was always going to be."""
    assert L.MANIFEST_URL.startswith("https://raw.githubusercontent.com/")
    assert L.MANIFEST_URL.endswith("/MangaTCT/main/manifest.json")
    assert "mangatct-releases" not in L.MANIFEST_URL, "no second repo"


def test_the_version_rule_is_the_apps():
    from mangatl import version as V
    for v in ("1.0.0", "v1.2.10", "1.1", "1.0.1-beta", "x"):
        assert L.parse_version(v) == V.parse(v), v
